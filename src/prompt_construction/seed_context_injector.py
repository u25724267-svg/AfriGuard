"""
AfriGuard - Prompt Construction: SeedContextInjector

Retrieves relevant seed documents from the database and formats them
as context snippets for injection into prompt templates.
"""

from __future__ import annotations

import random

import structlog
from sqlalchemy.orm import Session

from src.config.seed_context import SeedContextConfig, load_seed_context_config
from src.storage.db import SeedDocumentORM

logger = structlog.get_logger(__name__)


def _excerpt(text: str, max_chars: int) -> str:
    """Return a clean excerpt of a seed document."""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    # Try to cut at a sentence boundary.
    cut = text[:max_chars]
    last_period = cut.rfind(".")
    if last_period > max_chars // 2:
        return cut[: last_period + 1]
    return cut + "..."


class SeedContextInjector:
    """
    Retrieves seed documents and formats them for injection into prompts.

    The injector queries the DB for seed documents matching:
      - the target language
      - the harm domain of the prompt being generated

    It then formats them as a context block for the LLM system prompt.
    """

    def __init__(
        self,
        n_seeds: int | None = None,
        config: SeedContextConfig | None = None,
    ):
        """
        Args:
            n_seeds: Optional override for seed documents injected per prompt.
        """
        self._config = config or load_seed_context_config()
        self.n_seeds = n_seeds if n_seeds is not None else self._config.n_seeds

    def get_context_block(
        self,
        session: Session,
        language: str,
        harm_category: str,
        shuffle: bool | None = None,
    ) -> tuple[str, list[str]]:
        """
        Build a seed context block for the given language and harm category.

        Returns a formatted multi-line string ready for prompt injection plus
        the seed IDs used for provenance. If no seeds are found, returns an
        empty context and empty seed ID list.
        """
        if not self._config.enabled:
            return "", []

        should_shuffle = self._config.shuffle if shuffle is None else shuffle

        # Fetch language-matched seeds first, then filter JSON harm_domains in
        # Python. SQLAlchemy's generic JSON .contains() compiles to SQLite-
        # friendly LIKE expressions, which break on PostgreSQL JSON columns.
        language_pool: list[SeedDocumentORM] = (
            session.query(SeedDocumentORM)
            .filter(SeedDocumentORM.language == language)
            .limit(self.n_seeds * self._config.language_fallback_pool_multiplier)
            .all()
        )
        candidates = [
            seed
            for seed in language_pool
            if isinstance(seed.harm_domains, list) and harm_category in seed.harm_domains
        ][: self.n_seeds * self._config.exact_match_pool_multiplier]

        if not candidates and self._config.fallback_to_language:
            # Fall back: any seed for this language, used as cultural context.
            candidates = language_pool

        if not candidates:
            logger.warning(
                "seed_context_injector.no_seeds_found",
                language=language,
                harm_category=harm_category,
            )
            return "", []

        if should_shuffle:
            random.shuffle(candidates)

        selected = candidates[: self.n_seeds]
        seed_ids = [s.id for s in selected]

        excerpts = [
            _excerpt(s.text, self._config.max_excerpt_chars)
            for s in selected
        ]
        context_block = "\n---\n".join(f"- {e}" for e in excerpts)

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
        Build a context block from pre-fetched seed texts for testing.
        Returns (context_block, empty_seed_ids).
        """
        if not self._config.enabled:
            return "", []

        excerpts = [
            _excerpt(t, self._config.max_excerpt_chars)
            for t in seed_texts[: self.n_seeds]
        ]
        context_block = "\n---\n".join(f"- {e}" for e in excerpts)
        return context_block, []
