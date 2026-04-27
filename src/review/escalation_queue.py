"""
AfriGuard — Review: EscalationQueue

Manages S4 severity items, legally sensitive content, and annotator
disagreements that need senior researcher review.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from src.storage.db import AnnotationORM, CandidateResponseORM, GeneratedPromptORM

logger = structlog.get_logger(__name__)


class EscalationQueue:
    """
    Routes items to a senior review queue based on:
      - S4 severity (auto-escalate)
      - Annotator flagging decision
      - Annotator explicit escalation
    """

    def get_escalated_annotations(
        self, session: Session
    ) -> list[dict]:
        """Return all escalated annotation records for senior review."""
        annotations = (
            session.query(AnnotationORM)
            .filter(AnnotationORM.is_escalated == True)  # noqa: E712
            .order_by(AnnotationORM.created_at.asc())
            .all()
        )

        result = []
        for ann in annotations:
            candidate = session.query(CandidateResponseORM).get(ann.candidate_id)
            prompt = (
                session.query(GeneratedPromptORM).get(ann.prompt_id)
                if ann.prompt_id
                else None
            )
            result.append(
                {
                    "annotation_id": ann.id,
                    "candidate_id": ann.candidate_id,
                    "prompt_id": ann.prompt_id,
                    "language": ann.language,
                    "decision": ann.decision,
                    "escalation_reason": ann.escalation_reason,
                    "notes": ann.notes,
                    "prompt_text": prompt.prompt_text if prompt else "",
                    "response_text": candidate.response_text if candidate else "",
                    "harm_category": prompt.harm_category if prompt else "",
                    "severity": prompt.severity if prompt else "",
                }
            )
        return result

    def auto_escalate_s4(self, session: Session) -> int:
        """
        Find all S4 candidates without escalation annotations
        and create placeholder escalation records.

        Returns count of newly escalated items.
        """
        s4_prompts = (
            session.query(GeneratedPromptORM)
            .filter(GeneratedPromptORM.severity == "S4")
            .all()
        )

        escalated = 0
        for prompt in s4_prompts:
            candidates = (
                session.query(CandidateResponseORM)
                .filter(
                    CandidateResponseORM.prompt_id == prompt.id,
                    CandidateResponseORM.status == "passed_filter",
                )
                .all()
            )
            for candidate in candidates:
                # Check if already has an escalation annotation
                existing = (
                    session.query(AnnotationORM)
                    .filter(
                        AnnotationORM.candidate_id == candidate.id,
                        AnnotationORM.is_escalated == True,  # noqa: E712
                    )
                    .first()
                )
                if not existing:
                    ann = AnnotationORM(
                        id=str(uuid.uuid4()),
                        candidate_id=candidate.id,
                        prompt_id=prompt.id,
                        annotator_id="system_auto_escalate",
                        language=prompt.language,
                        decision="escalate",
                        is_escalated=True,
                        escalation_reason="S4 severity — automatic escalation",
                        created_at=datetime.now(tz=timezone.utc),
                    )
                    session.add(ann)
                    escalated += 1

        session.commit()
        if escalated:
            logger.info("escalation_queue.auto_escalated", count=escalated)
        return escalated
