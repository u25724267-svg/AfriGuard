"""
AfriGuard — Review: TaskAssigner

Builds review task queues from the *sampled* subset of candidates.

Only candidates marked ``sampled_for_review`` by the SampleSelector are
shown to researchers. The full ``passed_filter`` pool is exported to the
dataset automatically; the sample is reviewed to estimate quality and
catch systematic problems rather than to gate every item.

Each task groups all sampled candidates for a single prompt so the
researcher can compare and rank them in one session.
"""

from __future__ import annotations

from typing import Any
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from src.storage.db import CandidateResponseORM, GeneratedPromptORM

logger = structlog.get_logger(__name__)

# Maps language name to reviewer login ID
# These correspond to the reviewer_id values in pipeline.yaml
_LANGUAGE_REVIEWER_MAP = {
    "hausa": "reviewer_hausa",
    "sepedi": "reviewer_sepedi",
    "chichewa": "reviewer_chichewa",
    "northern_sotho": "reviewer_northern_sotho",
    "yao": "reviewer_yao",
    "yoruba": "reviewer_yoruba",
    "shona": "reviewer_shona",
}


class ReviewTask:
    """A bundle of candidates for one prompt, assigned to one reviewer."""

    def __init__(
        self,
        prompt_id: str,
        prompt_text: str,
        language: str,
        harm_category: str,
        severity: str,
        reviewer_id: str,
        candidates: list[dict[str, Any]],
    ):
        self.prompt_id = prompt_id
        self.prompt_text = prompt_text
        self.language = language
        self.harm_category = harm_category
        self.severity = severity
        self.reviewer_id = reviewer_id
        self.candidates = candidates  # list of candidate dicts


class TaskAssigner:
    """
    Builds ReviewTask queues from filtered candidates in the database.

    The review UI calls get_pending_tasks(reviewer_id) to fetch work.
    """

    def get_reviewer_id(self, language: str) -> str:
        reviewer = _LANGUAGE_REVIEWER_MAP.get(language.lower())
        if not reviewer:
            raise ValueError(f"No reviewer configured for language: {language}")
        return reviewer

    def get_pending_tasks(
        self,
        session: Session,
        reviewer_id: str,
        limit: int = 20,
    ) -> list[ReviewTask]:
        """
        Return pending review tasks for a given reviewer.

        Only shows candidates with status ``sampled_for_review`` — the
        stratified subset selected by SampleSelector. Candidates that
        passed the filter but were not sampled are exported automatically
        without requiring manual review.

        A task = one prompt + all its sampled candidates that have
        not yet been annotated.
        """
        # Find the language this reviewer covers
        language = None
        for lang, rev in _LANGUAGE_REVIEWER_MAP.items():
            if rev == reviewer_id:
                language = lang
                break

        if not language:
            logger.warning("task_assigner.unknown_reviewer", reviewer_id=reviewer_id)
            return []

        # Only surface the sampled subset — not the full passed_filter pool
        prompt_ids_with_pending_candidates = (
            select(CandidateResponseORM.prompt_id)
            .where(
                CandidateResponseORM.language == language,
                CandidateResponseORM.status == "sampled_for_review",
            )
            .distinct()
        )

        prompts = (
            session.query(GeneratedPromptORM)
            .filter(
                GeneratedPromptORM.language == language,
                GeneratedPromptORM.id.in_(prompt_ids_with_pending_candidates),
            )
            .limit(limit)
            .all()
        )

        tasks = []
        for prompt in prompts:
            candidates_orm = (
                session.query(CandidateResponseORM)
                .filter(
                    CandidateResponseORM.prompt_id == prompt.id,
                    CandidateResponseORM.status == "sampled_for_review",
                )
                .all()
            )

            candidate_dicts = [
                {
                    "id": c.id,
                    "response_text": c.response_text,
                    "response_type": c.response_type,
                    "quality_score": c.quality_score,
                    "similarity_score": c.similarity_score,
                }
                for c in candidates_orm
            ]

            task = ReviewTask(
                prompt_id=prompt.id,
                prompt_text=prompt.prompt_text,
                language=prompt.language,
                harm_category=prompt.harm_category,
                severity=prompt.severity,
                reviewer_id=reviewer_id,
                candidates=candidate_dicts,
            )
            tasks.append(task)

        logger.info(
            "task_assigner.tasks_fetched",
            reviewer_id=reviewer_id,
            language=language,
            task_count=len(tasks),
        )
        return tasks

    def count_pending_items(self, session: Session, reviewer_id: str) -> int:
        """Count candidate-level review items remaining for a reviewer."""
        language = None
        for lang, rev in _LANGUAGE_REVIEWER_MAP.items():
            if rev == reviewer_id:
                language = lang
                break

        if not language:
            return 0

        return (
            session.query(func.count(CandidateResponseORM.id))
            .filter(
                CandidateResponseORM.language == language,
                CandidateResponseORM.status == "sampled_for_review",
            )
            .scalar()
            or 0
        )

    def get_escalated_tasks(self, session: Session) -> list[dict[str, Any]]:
        """Return all S4 items and flagged items pending senior review."""
        prompts = (
            session.query(GeneratedPromptORM)
            .filter(GeneratedPromptORM.severity == "S4")
            .all()
        )
        return [
            {
                "prompt_id": p.id,
                "language": p.language,
                "harm_category": p.harm_category,
                "severity": p.severity,
                "prompt_text": p.prompt_text,
            }
            for p in prompts
        ]
