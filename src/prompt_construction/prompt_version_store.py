"""
AfriGuard — Prompt Construction: PromptVersionStore

Stores and retrieves versioned prompt templates in the database.
Every generation run records which template version it used,
enabling full reproducibility and diff tracking over time.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.storage.db import PromptTemplateORM

logger = structlog.get_logger(__name__)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PromptVersionStore:
    """
    Manages versioned storage of prompt templates.

    Each template is identified by (harm_category, version).
    The content_hash ensures immutability — if the template content
    changes, it must be saved as a new version.
    """

    def save(
        self,
        session: Session,
        template_id: str,
        version: str,
        harm_category: str,
        template_content: str,
        notes: str = "",
    ) -> PromptTemplateORM:
        """
        Persist a prompt template. Idempotent — no-ops if content_hash already exists.
        """
        content_hash = _hash_content(template_content)

        existing = (
            session.query(PromptTemplateORM)
            .filter(PromptTemplateORM.content_hash == content_hash)
            .first()
        )
        if existing:
            logger.debug("prompt_version_store.already_exists", template_id=template_id)
            return existing

        orm = PromptTemplateORM(
            id=template_id,
            version=version,
            content_hash=content_hash,
            harm_category=harm_category,
            template_content=template_content,
            notes=notes,
            created_at=datetime.now(tz=timezone.utc),
        )
        session.add(orm)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = (
                session.query(PromptTemplateORM)
                .filter(PromptTemplateORM.content_hash == content_hash)
                .first()
            )
            if existing:
                return existing
            raise
        logger.info(
            "prompt_version_store.saved",
            template_id=template_id,
            version=version,
            hash=content_hash[:12],
        )
        return orm

    def get(self, session: Session, template_id: str) -> PromptTemplateORM | None:
        return session.query(PromptTemplateORM).get(template_id)

    def get_hash(self, template_content: str) -> str:
        return _hash_content(template_content)

    def list_templates(self, session: Session, harm_category: str | None = None):
        q = session.query(PromptTemplateORM)
        if harm_category:
            q = q.filter(PromptTemplateORM.harm_category == harm_category)
        return q.order_by(PromptTemplateORM.created_at.desc()).all()
