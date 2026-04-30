"""
AfriGuard — Generation: GenerationJob

Orchestrates end-to-end generation of prompts and candidate responses
for a batch of (language, harm_category, severity) combinations.

Flow per item:
  1. Build system prompt (PromptBuilder)
  2. Call LLM to generate user-facing prompt (ModelRouter)
  3. Save generated prompt to DB
  4. For each of N candidates:
     a. Build response system prompt (safe or unsafe)
     b. Call LLM to generate response
     c. Save candidate to DB
  5. Track costs
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from src.generation.model_router import ModelRouter
from src.generation.cost_tracker import CostTracker
from src.prompt_construction.prompt_builder import PromptBuilder
from src.prompt_construction.prompt_version_store import PromptVersionStore
from src.prompt_construction.seed_context_injector import SeedContextInjector
from src.storage.db import GeneratedPromptORM, CandidateResponseORM
from src.taxonomy.harm_registry import get_registry
from src.config.languages import get_language_code

logger = structlog.get_logger(__name__)


class GenerationJob:
    """
    Executes a single generation batch for one (language, harm_category, severity) triple.

    Args:
        language:              Target language name
        harm_category:         Harm category ID (e.g. 'H01')
        severity:              Severity code (e.g. 'S2')
        model_id:              LLM model to use
        n_candidates:          Number of candidate responses per prompt
        run_id:                Pipeline run ID for grouping
        prompt_model_id:       Model for prompt generation (defaults to model_id)
    """

    def __init__(
        self,
        language: str,
        harm_category: str,
        severity: str,
        model_id: str = "gpt-4o",
        n_candidates: int = 4,
        run_id: str | None = None,
        prompt_model_id: str | None = None,
    ):
        self.language = language
        self.harm_category = harm_category
        self.severity = severity
        self.model_id = model_id
        self.prompt_model_id = prompt_model_id or model_id
        self.n_candidates = n_candidates
        self.run_id = run_id or str(uuid.uuid4())

        self._router = ModelRouter()
        self._builder = PromptBuilder()
        self._injector = SeedContextInjector()
        self._version_store = PromptVersionStore()
        self._cost_tracker = CostTracker()
        self._registry = get_registry()

    def run(self, session: Session, n_prompts: int = 1) -> list[str]:
        """
        Generate n_prompts prompts with n_candidates responses each.

        Returns:
            List of generated prompt IDs.
        """
        cat = self._registry.get_category(self.harm_category)

        # Check budget before starting
        self._cost_tracker.check_budget(session)

        prompt_ids = []
        for i in range(n_prompts):
            logger.info(
                "generation_job.generating_prompt",
                language=self.language,
                harm_category=self.harm_category,
                severity=self.severity,
                index=i + 1,
                total=n_prompts,
            )
            try:
                prompt_id = self._generate_one(session, cat)
                prompt_ids.append(prompt_id)
            except Exception as e:
                logger.error(
                    "generation_job.prompt_failed",
                    language=self.language,
                    harm_category=self.harm_category,
                    severity=self.severity,
                    error=str(e),
                )
                # Continue to next prompt rather than aborting the whole batch
                continue

        logger.info(
            "generation_job.batch_complete",
            generated=len(prompt_ids),
            requested=n_prompts,
        )
        return prompt_ids

    def _generate_one(self, session: Session, cat: Any) -> str:
        """Generate a single prompt + N candidate responses. Returns prompt_id."""

        # --- Step 1: Build seed context ---
        try:
            seed_context_result = self._injector.get_context_block(
                session=session,
                language=self.language,
                harm_category=self.harm_category,
            )
            if isinstance(seed_context_result, tuple):
                seed_context, seed_ids = seed_context_result
            else:
                seed_context, seed_ids = seed_context_result, []
        except Exception:
            seed_context, seed_ids = "", []

        # --- Step 2: Build and version the system prompt ---
        legal_context = self._builder.get_legal_context(
            language=self.language,
            harm_category=self.harm_category,
        )
        system_prompt = self._builder.build_system_prompt(
            language=self.language,
            harm_category=self.harm_category,
            severity=self.severity,
            seed_context=seed_context,
        )
        entities_injected = self._builder.get_entities_injected(self.language)
        template_hash = self._version_store.get_hash(system_prompt)

        # BUG FIX: template_id must be unique per *content*, not just per
        # harm_category. Different language/severity/seed combinations produce
        # different system prompts but previously all shared the same ID
        # (e.g. "H01_v1"), causing a primary-key conflict after the first
        # variant was inserted. We now derive the ID from the content hash
        # so every distinct prompt template gets its own immutable record.
        template_id = f"{self.harm_category}_{self.language}_{self.severity}_{template_hash[:8]}"

        self._version_store.save(
            session=session,
            template_id=template_id,
            version="1.0.0",
            harm_category=self.harm_category,
            template_content=system_prompt,
        )


        # --- Step 3: Generate the user-facing prompt ---
        user_message = (
            f"Generate a {self.severity} severity user prompt in {self.language} "
            f"for the harm category '{cat.name}'."
        )
        prompt_response = self._router.generate(
            model_id=self.prompt_model_id,
            system_prompt=system_prompt,
            user_message=user_message,
        )

        # Track cost
        self._cost_tracker.record(
            session=session,
            run_id=self.run_id,
            language=self.language,
            harm_category=self.harm_category,
            model_id=self.prompt_model_id,
            job_type="prompt_gen",
            prompt_tokens=prompt_response.prompt_tokens,
            completion_tokens=prompt_response.completion_tokens,
            cost_usd=prompt_response.cost_usd,
        )

        prompt_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)

        # Subcategory: randomly pick one from the category's list
        subcategory = (
            random.choice(cat.subcategories) if cat.subcategories else None
        )

        # --- Step 4: Save generated prompt to DB ---
        prompt_orm = GeneratedPromptORM(
            id=prompt_id,
            language=self.language,
            language_code=self._get_lang_code(self.language),
            harm_category=self.harm_category,
            harm_category_name=cat.name,
            severity=self.severity,
            subcategory=subcategory,
            prompt_text=prompt_response.text,
            system_prompt_used=system_prompt,
            prompt_template_id=template_id,
            prompt_template_version="1.0.0",
            prompt_template_hash=template_hash,
            seed_document_ids=seed_ids,
            legal_context_used=legal_context,
            entities_injected=entities_injected,
            model_used=self.prompt_model_id,
            generation_params={"temperature": 0.9, "max_tokens": 256},
            prompt_tokens=prompt_response.prompt_tokens,
            completion_tokens=prompt_response.completion_tokens,
            cost_usd=prompt_response.cost_usd,
            status="pending_response",
            created_at=now,
            run_id=self.run_id,
        )
        session.add(prompt_orm)
        session.flush()

        # --- Step 5: Generate N candidate responses ---
        # Half safe, half unsafe (rounded)
        n_safe = self.n_candidates // 2
        n_unsafe = self.n_candidates - n_safe

        candidates_generated = 0
        for resp_type, count in [("safe", n_safe), ("unsafe", n_unsafe)]:
            for idx in range(count):
                candidate_id = str(uuid.uuid4())
                resp_sys_prompt = self._builder.build_response_system_prompt(
                    language=self.language,
                    harm_category=self.harm_category,
                    severity=self.severity,
                    response_type=resp_type,
                )
                try:
                    resp = self._router.generate(
                        model_id=self.model_id,
                        system_prompt=resp_sys_prompt,
                        user_message=prompt_response.text,
                    )
                    self._cost_tracker.record(
                        session=session,
                        run_id=self.run_id,
                        language=self.language,
                        harm_category=self.harm_category,
                        model_id=self.model_id,
                        job_type="response_gen",
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        cost_usd=resp.cost_usd,
                    )

                    cand_orm = CandidateResponseORM(
                        id=candidate_id,
                        prompt_id=prompt_id,
                        language=self.language,
                        language_code=self._get_lang_code(self.language),
                        harm_category=self.harm_category,
                        severity=self.severity,
                        candidate_index=candidates_generated,
                        response_text=resp.text,
                        response_type=resp_type,
                        model_used=self.model_id,
                        generation_params={"temperature": 0.9, "max_tokens": 1024},
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        cost_usd=resp.cost_usd,
                        status="raw",
                        created_at=datetime.now(tz=timezone.utc),
                        run_id=self.run_id,
                    )
                    session.add(cand_orm)
                    candidates_generated += 1

                except Exception as e:
                    logger.warning(
                        "generation_job.candidate_failed",
                        prompt_id=prompt_id,
                        resp_type=resp_type,
                        error=str(e),
                    )

        # Update prompt status
        prompt_orm.status = "generated"
        session.commit()

        logger.info(
            "generation_job.prompt_complete",
            prompt_id=prompt_id,
            candidates=candidates_generated,
        )
        return prompt_id

    @staticmethod
    def _get_lang_code(language: str) -> str:
        try:
            return get_language_code(language)
        except KeyError:
            return "xx"
