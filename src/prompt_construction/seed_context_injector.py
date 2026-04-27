"""
AfriGuard — Prompt Construction: SeedContextInjector

Retrieves relevant seed documents from the database and formats them
as context snippets for injection into prompt templates.
"""

from __future__ import annotations

import random

import structlog
from sqlalchemy.orm import Session

from src.storage.db import SeedDocumentORM

logger = structlog.get_logger(__name__)

# Maximum characters to include from a single seed document
MAX_SEED_EXCERPT_CHARS = 400


def _excerpt(text: str, max_chars: int = MAX_SEED_EXCERPT_CHARS) -> str:
    """Return a clean excerpt of a seed document."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # Try to cut at a sentence boundary
    cut = text[:max_chars]
    last_period = cut.rfind(".")
    if last_period > max_chars // 2:
        return cut[: last_period + 1]
    return cut + "…"


class SeedContextInjector:
    """
    Retrieves seed documents and formats them for injection into prompts.

    The injector queries the DB for seed documents matching:
      - the target language
      - the harm domain of the prompt being generated

    It then formats them as a context block for the LLM system prompt.
    """

    def __init__(self, n_seeds: int = 5):
        """
        Args:
            n_seeds: Number of seed documents to inject per prompt.
        """
        self.n_seeds = n_seeds

    def get_context_block(
        self,
        session: Session,
        language: str,
        harm_category: str,
        shuffle: bool = True,
    ) -> str:
        """
        Build a seed context block for the given language and harm category.

        Returns a formatted multi-line string ready for prompt injection.
        If no seeds are found, returns an empty string (generation continues
        without seed context, relying on cultural entity injection instead).
        """
        # Fetch more than needed so we can randomly sample
        candidates: list[SeedDocumentORM] = (
            session.query(SeedDocumentORM)
            .filter(
                SeedDocumentORM.language == language,
                SeedDocumentORM.harm_domains.contains(harm_category),
            )
            .limit(self.n_seeds * 5)
            .all()
        )

        if not candidates:
            # Fall back: any seed for this language (used as cultural context)
            candidates = (
                session.query(SeedDocumentORM)
                .filter(SeedDocumentORM.language == language)
                .limit(self.n_seeds * 3)
                .all()
            )

        if not candidates:
            logger.warning(
                "seed_context_injector.no_seeds_found",
                language=language,
                harm_category=harm_category,
            )
            return ""

        if shuffle:
            random.shuffle(candidates)

        selected = candidates[: self.n_seeds]
        seed_ids = [s.id for s in selected]

        excerpts = [_excerpt(s.text) for s in selected]
        context_block = "\n---\n".join(f"• {e}" for e in excerpts)

        logger.debug(
            "seed_context_injector.context_built",
            language=language,
            harm_category=harm_category,
            n_seeds=len(selected),
        )

        return context_block, seed_ids

    def get_context_block_no_db(
        self, seed_texts: list[str]
    ) -> tuple[str, list[str]]:
        """
        Build a context block from pre-fetched seed texts (for testing).
        Returns (context_block, empty_seed_ids).
        """
        excerpts = [_excerpt(t) for t in seed_texts[: self.n_seeds]]
        context_block = "\n---\n".join(f"• {e}" for e in excerpts)
        return context_block, []
