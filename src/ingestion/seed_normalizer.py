"""
AfriGuard — Ingestion: SeedNormalizer

Converts raw adapter records into validated SeedDocument instances.
Applies text cleaning, length filtering, and language validation.
"""

from __future__ import annotations

import re
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any

import structlog

from src.config.languages import get_language_code
from src.schemas.seed import SeedDocument

logger = structlog.get_logger(__name__)

# Minimum/maximum character counts for a usable seed document
MIN_CHARS = 30
MAX_CHARS = 5000


def _clean_text(text: str) -> str:
    """Basic text cleaning: normalize whitespace, strip boilerplate."""
    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove null bytes and control characters (except newlines)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text.strip()


class SeedNormalizer:
    """
    Converts raw records from adapters into validated SeedDocument instances.

    Handles:
      - Text cleaning
      - Length filtering
      - Multi-language assignment when a source covers several languages
      - Provenance hash computation (via SeedDocument model validator)
    """

    def normalize(
        self,
        source_config: dict[str, Any],
        raw_records: list[dict[str, Any]],
        target_language: str | None = None,
    ) -> tuple[list[SeedDocument], int]:
        """
        Normalize raw records for a given source.

        Args:
            source_config:   Entry from seed_sources.yaml
            raw_records:     Records returned by an adapter
            target_language: If set, override the source's language list
                             (use when calling per-language)

        Returns:
            (documents, skipped_count) tuple.
        """
        source_id = source_config.get("id", "unknown")
        source_name = source_config.get("name", source_id)
        source_split = source_config.get("hf_split", "train")
        harm_domains = source_config.get("harm_domains", [])
        license_str = source_config.get("license", "unknown")

        # Determine languages this source applies to
        if target_language:
            languages = [target_language]
        else:
            languages = source_config.get("languages", ["unknown"])

        documents: list[SeedDocument] = []
        skipped = 0

        for raw in raw_records:
            raw_text = raw.get("text", "")
            metadata = raw.get("metadata", {})

            if not raw_text:
                skipped += 1
                continue

            cleaned = _clean_text(raw_text)

            if len(cleaned) < MIN_CHARS:
                skipped += 1
                continue
            if len(cleaned) > MAX_CHARS:
                cleaned = cleaned[:MAX_CHARS]

            # BUG FIX: Previously only languages[0] was used, which starved
            # all other languages in multi-language sources of seed context.
            # We now create one SeedDocument per language in the source's
            # language list so every language gets equal seed coverage.
            # The provenance_hash includes the language to keep records unique.
            now = datetime.now(tz=timezone.utc)
            for lang in languages:
                try:
                    lang_code = get_language_code(lang)
                except KeyError:
                    lang_code = "xx"
                try:
                    doc = SeedDocument(
                        id=str(uuid.uuid4()),
                        source_id=source_id,
                        source_name=source_name,
                        source_split=source_split,
                        language=lang,
                        language_code=lang_code,
                        harm_domains=harm_domains,
                        text=cleaned,
                        original_text=raw_text,
                        metadata=metadata,
                        license=license_str,
                        fetched_at=now,
                        # Provenance hash includes language so per-language
                        # copies get distinct hashes and are stored separately.
                        provenance_hash=hashlib.sha256(
                            f"{source_id}::{lang}::{raw_text}".encode("utf-8")
                        ).hexdigest(),
                    )
                    documents.append(doc)
                except Exception as e:
                    logger.warning(
                        "seed_normalizer.validation_failed",
                        source_id=source_id,
                        language=lang,
                        error=str(e),
                    )
                    skipped += 1


        logger.info(
            "seed_normalizer.normalized",
            source_id=source_id,
            documents=len(documents),
            skipped=skipped,
        )
        return documents, skipped
