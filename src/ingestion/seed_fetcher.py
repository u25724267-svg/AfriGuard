"""
AfriGuard — Ingestion: SeedFetcher

Orchestrates fetching of all seed datasets defined in configs/seed_sources.yaml.
Dispatches to the appropriate adapter (HuggingFace or local) per source.
Supports per-source max_samples for PoC runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
import structlog

from src.ingestion.adapters.hf_adapter import HFAdapter
from src.ingestion.adapters.local_adapter import LocalAdapter

logger = structlog.get_logger(__name__)

_DEFAULT_SOURCES_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "seed_sources.yaml"
)


class SeedFetcher:
    """
    Fetches all seed datasets defined in seed_sources.yaml.

    Usage:
        fetcher = SeedFetcher()
        raw_batches = fetcher.fetch_all(max_samples_per_source=200)
        # raw_batches: list of (source_config, list[dict])
    """

    def __init__(
        self,
        sources_path: Path = _DEFAULT_SOURCES_PATH,
        hf_token: str | None = None,
    ):
        self._sources_path = sources_path
        self._hf_adapter = HFAdapter(hf_token=hf_token)
        self._local_adapter = LocalAdapter()
        self._sources: list[dict[str, Any]] = []
        self._load_sources()

    def _load_sources(self) -> None:
        with open(self._sources_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._sources = data.get("sources", [])
        logger.info("seed_fetcher.sources_loaded", count=len(self._sources))

    def fetch_all(
        self,
        max_samples_per_source: int | None = None,
        languages: list[str] | None = None,
        source_ids: list[str] | None = None,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """
        Fetch all (or a subset of) seed sources.

        Args:
            max_samples_per_source: Limit records per source (PoC mode).
            languages:              Only fetch sources relevant to these languages.
            source_ids:             Only fetch sources with these IDs.

        Returns:
            List of (source_config, records) tuples.
        """
        results = []
        for source in self._sources:
            sid = source.get("id", "unknown")

            if source.get("enabled", True) is False:
                logger.info("seed_fetcher.source_disabled", source_id=sid)
                continue

            # Filter by source ID if requested
            if source_ids and sid not in source_ids:
                continue

            # Filter by language if requested
            source_langs = source.get("languages", [])
            if languages:
                if not any(lang in source_langs for lang in languages):
                    continue

            logger.info("seed_fetcher.fetching_source", source_id=sid)

            try:
                target_languages = [
                    lang for lang in (languages or []) if lang in source_langs
                ]
                if target_languages:
                    for lang in target_languages:
                        source_for_language = dict(source)
                        source_for_language["languages"] = [lang]
                        records = self._fetch_source(
                            source_for_language,
                            max_samples=max_samples_per_source,
                            language=lang,
                        )
                        logger.info(
                            "seed_fetcher.source_done",
                            source_id=sid,
                            language=lang,
                            records=len(records),
                        )
                        results.append((source_for_language, records))
                else:
                    records = self._fetch_source(source, max_samples=max_samples_per_source)
                    logger.info("seed_fetcher.source_done", source_id=sid, records=len(records))
                    results.append((source, records))
            except Exception as e:
                logger.error("seed_fetcher.source_failed", source_id=sid, error=str(e))
                # Non-fatal: continue with other sources
                results.append((source, []))

        return results

    def _fetch_source(
        self,
        source: dict[str, Any],
        max_samples: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        source_type = source.get("type", "huggingface")

        if source_type == "huggingface":
            hf_config = source.get("hf_config")
            hf_config_by_language = source.get("hf_config_by_language", {})
            if language and hf_config_by_language:
                hf_config = hf_config_by_language.get(language, hf_config)

            return self._hf_adapter.fetch(
                hf_path=source["hf_path"],
                hf_config=hf_config,
                split=source.get("hf_split", "train"),
                text_column=source.get("text_column", "text"),
                is_token_list=source.get("is_token_list", False),
                max_samples=max_samples,
            )
        elif source_type == "local":
            local_path = source.get("local_path")
            if not local_path:
                raise ValueError(f"Source '{source.get('id')}' has no local_path")
            return self._local_adapter.fetch(
                local_path=local_path,
                text_column=source.get("text_column", "text"),
                max_samples=max_samples,
            )
        else:
            raise ValueError(f"Unknown source type: {source_type}")
