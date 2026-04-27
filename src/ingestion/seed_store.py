"""
AfriGuard — Ingestion: SeedStore

Persists normalized SeedDocuments to the database.
Handles idempotency via provenance_hash uniqueness.
"""

from __future__ import annotations

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.schemas.seed import SeedDocument
from src.storage.db import SeedDocumentORM

logger = structlog.get_logger(__name__)


class SeedStore:
    """Writes SeedDocument instances to the database, deduplicating by provenance_hash."""

    def save_batch(
        self, documents: list[SeedDocument], session: Session
    ) -> tuple[int, int]:
        """
        Persist a batch of SeedDocuments.

        Returns:
            (inserted, skipped_duplicates) counts.
        """
        inserted = 0
        skipped = 0

        for doc in documents:
            orm = SeedDocumentORM(
                id=doc.id,
                source_id=doc.source_id,
                source_name=doc.source_name,
                source_split=doc.source_split,
                language=doc.language,
                language_code=doc.language_code,
                harm_domains=doc.harm_domains,
                text=doc.text,
                original_text=doc.original_text,
                metadata_=doc.metadata,
                license=doc.license,
                fetched_at=doc.fetched_at,
                provenance_hash=doc.provenance_hash,
            )
            try:
                session.add(orm)
                session.flush()
                inserted += 1
            except IntegrityError:
                session.rollback()
                skipped += 1

        session.commit()
        logger.info(
            "seed_store.batch_saved",
            inserted=inserted,
            skipped_duplicates=skipped,
        )
        return inserted, skipped

    def get_by_language_and_domain(
        self,
        session: Session,
        language: str,
        harm_domain: str,
        limit: int = 10,
    ) -> list[SeedDocumentORM]:
        """
        Retrieve seed documents for a given language and harm domain.
        Uses JSON containment check via LIKE (SQLite compatible).
        """
        results = (
            session.query(SeedDocumentORM)
            .filter(
                SeedDocumentORM.language == language,
                SeedDocumentORM.harm_domains.contains(harm_domain),
            )
            .limit(limit)
            .all()
        )
        return results

    def get_by_language(
        self,
        session: Session,
        language: str,
        limit: int = 50,
    ) -> list[SeedDocumentORM]:
        """Retrieve all seed documents for a given language."""
        return (
            session.query(SeedDocumentORM)
            .filter(SeedDocumentORM.language == language)
            .limit(limit)
            .all()
        )

    def count(self, session: Session) -> dict[str, int]:
        """Return count of seed documents per language."""
        from sqlalchemy import func
        rows = (
            session.query(SeedDocumentORM.language, func.count(SeedDocumentORM.id))
            .group_by(SeedDocumentORM.language)
            .all()
        )
        return {lang: count for lang, count in rows}
