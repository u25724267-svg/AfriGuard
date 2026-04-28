"""
AfriGuard — Assembly: QABuilder

Builds (prompt, safe_response) and (prompt, unsafe_response) pairs
for supervised fine-tuning (SFT) safety training.
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


class QABuilder:
    """Builds QA-style dataset items from approved annotated candidates."""

    def build(
        self,
        session: Session,
        dataset_version: str,
        run_id: str,
        language: str | None = None,
    ) -> int:
        query = session.query(GeneratedPromptORM)
        if language:
            query = query.filter(GeneratedPromptORM.language == language)
        prompts = query.all()

        created = 0
        for prompt in prompts:
            created += self._build_qa_for_prompt(session, prompt, dataset_version, run_id)

        session.commit()
        logger.info("qa_builder.built", language=language or "all", items=created)
        return created

    def _build_qa_for_prompt(
        self,
        session: Session,
        prompt: GeneratedPromptORM,
        dataset_version: str,
        run_id: str,
    ) -> int:
        candidates = (
            session.query(CandidateResponseORM)
            .filter(CandidateResponseORM.prompt_id == prompt.id)
            .all()
        )

        created = 0
        for cand in candidates:
            ann = (
                session.query(AnnotationORM)
                .filter(AnnotationORM.candidate_id == cand.id)
                .order_by(AnnotationORM.created_at.desc())
                .first()
            )
            if not ann or ann.decision != "approve":
                continue

            item_type = f"qa_{cand.response_type}"  # qa_safe or qa_unsafe
            existing = (
                session.query(DatasetItemORM)
                .filter(
                    DatasetItemORM.dataset_version == dataset_version,
                    DatasetItemORM.item_type == item_type,
                    DatasetItemORM.prompt_id == prompt.id,
                    DatasetItemORM.response_id == cand.id,
                )
                .first()
            )
            if existing:
                continue

            item = DatasetItemORM(
                id=str(uuid.uuid4()),
                item_type=item_type,
                language=prompt.language,
                language_code=prompt.language_code,
                harm_category=prompt.harm_category,
                harm_category_name=prompt.harm_category_name,
                severity=prompt.severity,
                prompt_id=prompt.id,
                prompt_text=prompt.prompt_text,
                response_id=cand.id,
                response_text=ann.suggested_edit or cand.response_text,
                seed_document_ids=prompt.seed_document_ids or [],
                prompt_template_id=prompt.prompt_template_id,
                annotator_ids=[ann.annotator_id],
                models_used=[cand.model_used],
                dataset_version=dataset_version,
                run_id=run_id,
                created_at=datetime.now(tz=timezone.utc),
            )
            session.add(item)
            created += 1

        return created
