"""
AfriGuard — Assembly: PreferenceBuilder

Builds RLHF-style preference pairs from annotated candidates.
For each prompt, pairs the highest-ranked annotated response (chosen)
against the lowest-ranked or rejected response (rejected).

Output format compatible with TRL (Transformer Reinforcement Learning)
and OpenRLHF preference datasets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from src.storage.db import (
    AnnotationORM,
    CandidateResponseORM,
    DatasetItemORM,
    GeneratedPromptORM,
)

logger = structlog.get_logger(__name__)


class PreferenceBuilder:
    """
    Builds preference pairs from reviewed candidates.

    Pair selection logic:
      - chosen  = candidate with lowest preference_rank (1 = best) OR approved decision
      - rejected = candidate with highest preference_rank OR rejected decision
      - If only one candidate is approved, pair it with the best rejected candidate
    """

    def build(
        self,
        session: Session,
        dataset_version: str,
        run_id: str,
        language: str | None = None,
    ) -> int:
        """
        Build preference pairs for all reviewed prompts.

        Returns:
            Count of preference pairs created.
        """
        # Query prompts that have at least one approved AND one rejected candidate
        query = session.query(GeneratedPromptORM)
        if language:
            query = query.filter(GeneratedPromptORM.language == language)

        prompts = query.all()
        created = 0

        for prompt in prompts:
            pairs_created = self._build_pairs_for_prompt(
                session, prompt, dataset_version, run_id
            )
            created += pairs_created

        session.commit()
        logger.info(
            "preference_builder.built",
            language=language or "all",
            pairs=created,
        )
        return created

    def _build_pairs_for_prompt(
        self,
        session: Session,
        prompt: GeneratedPromptORM,
        dataset_version: str,
        run_id: str,
    ) -> int:
        # Get all annotations for candidates of this prompt
        candidates = (
            session.query(CandidateResponseORM)
            .filter(CandidateResponseORM.prompt_id == prompt.id)
            .all()
        )
        if not candidates:
            return 0

        # Get annotations keyed by candidate_id
        annotations: dict[str, AnnotationORM] = {}
        for cand in candidates:
            ann = (
                session.query(AnnotationORM)
                .filter(AnnotationORM.candidate_id == cand.id)
                .order_by(AnnotationORM.created_at.desc())
                .first()
            )
            if ann:
                annotations[cand.id] = ann

        approved = [
            c for c in candidates
            if annotations.get(c.id) and annotations[c.id].decision == "approve"
        ]
        rejected = [
            c for c in candidates
            if annotations.get(c.id) and annotations[c.id].decision == "reject"
        ]

        if not approved or not rejected:
            return 0

        # Sort by preference rank if available
        def rank_key(c):
            ann = annotations.get(c.id)
            return ann.preference_rank or 999 if ann else 999

        approved.sort(key=rank_key)
        rejected.sort(key=rank_key, reverse=True)

        chosen = approved[0]
        rejected_cand = rejected[0]

        # Collect annotator IDs
        annotator_ids = list({
            ann.annotator_id
            for ann in annotations.values()
        })

        item = DatasetItemORM(
            id=str(uuid.uuid4()),
            item_type="preference_pair",
            language=prompt.language,
            language_code=prompt.language_code,
            harm_category=prompt.harm_category,
            harm_category_name=prompt.harm_category_name,
            severity=prompt.severity,
            prompt_id=prompt.id,
            prompt_text=prompt.prompt_text,
            chosen_response_id=chosen.id,
            chosen_response_text=chosen.response_text,
            rejected_response_id=rejected_cand.id,
            rejected_response_text=rejected_cand.response_text,
            seed_document_ids=prompt.seed_document_ids or [],
            prompt_template_id=prompt.prompt_template_id,
            annotator_ids=annotator_ids,
            models_used=list({chosen.model_used, rejected_cand.model_used}),
            dataset_version=dataset_version,
            run_id=run_id,
            created_at=datetime.now(tz=timezone.utc),
        )
        session.add(item)
        return 1
