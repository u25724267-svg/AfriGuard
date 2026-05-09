"""Generation job that adapts PKU source prompts into AfriGuard prompts."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import structlog
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from src.config.generation import load_generation_config
from src.config.languages import get_language_code
from src.generation.cost_tracker import CostTracker
from src.generation.model_router import ModelRouter
from src.prompt_construction.prompt_builder import PromptBuilder
from src.prompt_construction.prompt_version_store import PromptVersionStore
from src.prompt_construction.seed_context_injector import SeedContextInjector
from src.storage.db import CandidateResponseORM, GeneratedPromptORM, SourcePromptORM
from src.taxonomy.harm_registry import get_registry

logger = structlog.get_logger(__name__)


class PKUAdaptedGenerationJob:
    """
    Adapt PKU source prompts into AfriGuard prompts and generate candidate responses.
    """

    def __init__(
        self,
        language: str,
        harm_category: str,
        severity: str,
        model_id: str = "gpt-5.4",
        n_candidates: int = 4,
        run_id: str | None = None,
        prompt_model_id: str | None = None,
        source_dataset: str | None = None,
        generate_candidates: bool = True,
    ):
        self.language = language
        self.harm_category = harm_category
        self.severity = severity
        self.model_id = model_id
        self.prompt_model_id = prompt_model_id or model_id
        self.n_candidates = n_candidates
        self.run_id = run_id or str(uuid.uuid4())
        self.source_dataset = source_dataset
        self.generate_candidates = generate_candidates

        self._router = ModelRouter()
        self._builder = PromptBuilder()
        self._injector = SeedContextInjector()
        self._version_store = PromptVersionStore()
        self._cost_tracker = CostTracker()
        self._registry = get_registry()
        self._generation_config = load_generation_config()

    def run(
        self,
        session: Session,
        n_prompts: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        cat = self._registry.get_category(self.harm_category)
        self._cost_tracker.check_budget(session)

        prompt_ids = []
        for i in range(n_prompts):
            logger.info(
                "pku_adapted_generation_job.adapting_prompt",
                language=self.language,
                harm_category=self.harm_category,
                severity=self.severity,
                index=i + 1,
                total=n_prompts,
            )
            try:
                source_prompt = self._select_source_prompt(session)
                if source_prompt is None:
                    raise ValueError(
                        "No PKU source prompts available. Run `afriguard ingest-pku-prompts` first."
                    )
                prompt_id = self._generate_one(session, cat, source_prompt)
                prompt_ids.append(prompt_id)
                if progress_callback:
                    progress_callback(prompt_id)
            except Exception as e:
                session.rollback()
                logger.error(
                    "pku_adapted_generation_job.prompt_failed",
                    language=self.language,
                    harm_category=self.harm_category,
                    severity=self.severity,
                    error=str(e),
                )
                continue

        logger.info(
            "pku_adapted_generation_job.batch_complete",
            generated=len(prompt_ids),
            requested=n_prompts,
        )
        return prompt_ids

    def _select_source_prompt(self, session: Session) -> SourcePromptORM | None:
        used_source_ids = self._used_source_prompt_ids(session)
        base_query = session.query(SourcePromptORM)
        if self.source_dataset:
            base_query = base_query.filter(SourcePromptORM.source_dataset == self.source_dataset)
        if used_source_ids:
            base_query = base_query.filter(SourcePromptORM.id.notin_(used_source_ids))

        exact = (
            base_query.filter(
                SourcePromptORM.mapped_harm_category == self.harm_category,
                or_(
                    SourcePromptORM.mapped_severity == self.severity,
                    SourcePromptORM.mapped_severity.is_(None),
                ),
            )
            .order_by(func.random())
            .first()
        )
        if exact:
            return exact

        category_match = (
            base_query.filter(
                or_(
                    SourcePromptORM.mapped_harm_category == self.harm_category,
                    SourcePromptORM.mapped_harm_category.is_(None),
                )
            )
            .order_by(func.random())
            .first()
        )
        if category_match:
            return category_match

        fallback_query = session.query(SourcePromptORM)
        if self.source_dataset:
            fallback_query = fallback_query.filter(SourcePromptORM.source_dataset == self.source_dataset)
        return fallback_query.order_by(func.random()).first()

    def _used_source_prompt_ids(self, session: Session) -> set[str]:
        rows = (
            session.query(GeneratedPromptORM.generation_params)
            .filter(
                GeneratedPromptORM.run_id == self.run_id,
                GeneratedPromptORM.language == self.language,
                GeneratedPromptORM.harm_category == self.harm_category,
                GeneratedPromptORM.severity == self.severity,
            )
            .all()
        )
        used = set()
        for (params,) in rows:
            if isinstance(params, dict) and params.get("source_prompt_table_id"):
                used.add(str(params["source_prompt_table_id"]))
        return used

    def _generate_one(self, session: Session, cat: Any, source_prompt: SourcePromptORM) -> str:
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

        legal_context = self._builder.get_legal_context(
            language=self.language,
            harm_category=self.harm_category,
        )
        system_prompt = self._builder.build_pku_adaptation_system_prompt(
            language=self.language,
            harm_category=self.harm_category,
            severity=self.severity,
            source_prompt=source_prompt.prompt_text,
            seed_context=seed_context,
        )
        entities_injected = self._builder.get_entities_injected(self.language)
        template_hash = self._version_store.get_hash(system_prompt)
        template_id = (
            f"pku_adapted_{self.harm_category}_{self.language}_{self.severity}_{template_hash[:8]}"
        )
        self._version_store.save(
            session=session,
            template_id=template_id,
            version=self._builder.template_version,
            harm_category=self.harm_category,
            template_content=system_prompt,
        )

        user_message = self._builder.build_pku_adaptation_user_message(
            language=self.language,
            harm_category=self.harm_category,
            severity=self.severity,
            source_prompt=source_prompt.prompt_text,
        )
        prompt_response = self._router.generate(
            model_id=self.prompt_model_id,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=self._generation_config.prompt_generation.temperature,
            max_tokens=self._generation_config.prompt_generation.max_tokens,
        )
        self._cost_tracker.record(
            session=session,
            run_id=self.run_id,
            language=self.language,
            harm_category=self.harm_category,
            model_id=self.prompt_model_id,
            job_type="prompt_adaptation",
            prompt_tokens=prompt_response.prompt_tokens,
            completion_tokens=prompt_response.completion_tokens,
            cost_usd=prompt_response.cost_usd,
        )

        prompt_id = str(uuid.uuid4())
        subcategory = random.choice(cat.subcategories) if cat.subcategories else None
        generation_params = self._generation_config.prompt_generation.to_dict()
        generation_params.update(
            {
                "generation_mode": "pku_context_regeneration",
                "legacy_generation_mode": "pku_adapted",
                "prompt_pipeline": (
                    "pku_context_regeneration_inline"
                    if self.generate_candidates
                    else "pku_context_regeneration_prompt_only"
                ),
                "response_strategy": (
                    "inline_generation"
                    if self.generate_candidates
                    else "batch_response_generation"
                ),
                "source_dataset": source_prompt.source_dataset,
                "source_split": source_prompt.source_split,
                "source_prompt_table_id": source_prompt.id,
                "source_prompt_id": source_prompt.source_prompt_id,
                "source_prompt_hash": source_prompt.provenance_hash,
                "source_prompt_text": source_prompt.prompt_text,
                "source_raw_harm_category": source_prompt.raw_harm_category,
                "source_mapped_harm_category": source_prompt.mapped_harm_category,
                "source_raw_severity": source_prompt.raw_severity,
                "source_mapped_severity": source_prompt.mapped_severity,
                "source_license": source_prompt.license,
                "adaptation_model": self.prompt_model_id,
                "adaptation_method": "pku_context_injection_regeneration",
                "prompt_only": not self.generate_candidates,
            }
        )

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
            prompt_template_version=self._builder.template_version,
            prompt_template_hash=template_hash,
            seed_document_ids=seed_ids,
            legal_context_used=legal_context,
            entities_injected=entities_injected,
            model_used=self.prompt_model_id,
            generation_params=generation_params,
            prompt_tokens=prompt_response.prompt_tokens,
            completion_tokens=prompt_response.completion_tokens,
            cost_usd=prompt_response.cost_usd,
            status="pending_response",
            created_at=datetime.now(tz=timezone.utc),
            run_id=self.run_id,
        )
        session.add(prompt_orm)
        session.flush()

        if self.generate_candidates:
            candidates_generated = self._generate_candidates(session, prompt_id, prompt_response.text)
            prompt_orm.status = "generated"
        else:
            candidates_generated = 0
            prompt_orm.status = "pending_response"
        session.commit()

        logger.info(
            "pku_adapted_generation_job.prompt_complete",
            prompt_id=prompt_id,
            source_prompt_id=source_prompt.source_prompt_id,
            candidates=candidates_generated,
        )
        return prompt_id

    def _generate_candidates(self, session: Session, prompt_id: str, prompt_text: str) -> int:
        n_safe, n_unsafe = self._generation_config.candidate_mix.response_type_counts(
            self.n_candidates
        )

        candidates_generated = 0
        for resp_type, count in [("safe", n_safe), ("unsafe", n_unsafe)]:
            for _ in range(count):
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
                        user_message=prompt_text,
                        temperature=self._generation_config.response_generation.temperature,
                        max_tokens=self._generation_config.response_generation.max_tokens,
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

                    session.add(
                        CandidateResponseORM(
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
                            generation_params=self._generation_config.response_generation.to_dict(),
                            prompt_tokens=resp.prompt_tokens,
                            completion_tokens=resp.completion_tokens,
                            cost_usd=resp.cost_usd,
                            status="raw",
                            created_at=datetime.now(tz=timezone.utc),
                            run_id=self.run_id,
                        )
                    )
                    candidates_generated += 1
                except Exception as e:
                    logger.warning(
                        "pku_adapted_generation_job.candidate_failed",
                        prompt_id=prompt_id,
                        resp_type=resp_type,
                        error=str(e),
                    )

        return candidates_generated

    @staticmethod
    def _get_lang_code(language: str) -> str:
        try:
            return get_language_code(language)
        except KeyError:
            return "xx"
