"""
AfriGuard — Assembly: ClassificationBuilder

Builds (text, harm_label, severity_label) items for moderation/classification
model training.
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


class ClassificationBuilder:
    """
    Builds classification dataset items.

    For each approved candidate:
      - text = the response text (or prompt text for prompt classification)
      - harm_label = annotator-provided label (or model label if not corrected)
      - severity_label = annotator-provided severity
    """

    def build(
        self,
        session: Session,
        dataset_version: str,
        run_id: str,
        language: str | None = None,
        classify_prompts: bool = True,
        classify_responses: bool = True,
    ) -> int:
        query = session.query(GeneratedPromptORM)
        if language:
            query = query.filter(GeneratedPromptORM.language == language)
        prompts = query.all()

        created = 0
        for prompt in prompts:
            created += self._build_for_prompt(
                session, prompt, dataset_version, run_id,
                classify_prompts, classify_responses
            )

        session.commit()
        logger.info("classification_builder.built", language=language or "all", items=created)
        return created

    def _build_for_prompt(
        self,
        session: Session,
        prompt: GeneratedPromptORM,
        dataset_version: str,
        run_id: str,
        classify_prompts: bool,
        classify_responses: bool,
    ) -> int:
        created = 0

        if classify_prompts:
            # Classify the prompt itself
            item = DatasetItemORM(
                id=str(uuid.uuid4()),
                item_type="classification",
                language=prompt.language,
                language_code=prompt.language_code,
                harm_category=prompt.harm_category,
                harm_category_name=prompt.harm_category_name,
                severity=prompt.severity,
                prompt_id=prompt.id,
                prompt_text=prompt.prompt_text,
                classification_text=prompt.prompt_text,
                harm_label=prompt.harm_category,
                severity_label=prompt.severity,
                seed_document_ids=prompt.seed_document_ids or [],
                prompt_template_id=prompt.prompt_template_id,
                annotator_ids=[],
                models_used=[prompt.model_used],
                dataset_version=dataset_version,
                run_id=run_id,
                created_at=datetime.now(tz=timezone.utc),
            )
            session.add(item)
            created += 1

        if classify_responses:
            candidates = (
                session.query(CandidateResponseORM)
                .filter(CandidateResponseORM.prompt_id == prompt.id)
                .all()
            )
            for cand in candidates:
                ann = (
                    session.query(AnnotationORM)
                    .filter(AnnotationORM.candidate_id == cand.id)
                    .order_by(AnnotationORM.created_at.desc())
                    .first()
                )
                if not ann or ann.decision not in ("approve", "reject"):
                    continue

                harm_label = (ann.harm_label or prompt.harm_category)
                severity_label = (ann.severity_label or prompt.severity)

                item = DatasetItemORM(
                    id=str(uuid.uuid4()),
                    item_type="classification",
                    language=prompt.language,
                    language_code=prompt.language_code,
                    harm_category=prompt.harm_category,
                    harm_category_name=prompt.harm_category_name,
                    severity=prompt.severity,
                    prompt_id=prompt.id,
                    prompt_text=prompt.prompt_text,
                    classification_text=cand.response_text,
                    harm_label=harm_label,
                    severity_label=severity_label,
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
