"""
AfriGuard - Ingestion: remote URL file adapter.

Downloads simple public seed files and normalizes them through LocalAdapter.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from src.ingestion.adapters.local_adapter import LocalAdapter

logger = structlog.get_logger(__name__)


class URLAdapter:
    """Fetch public .txt, .csv, .json, and .jsonl files over HTTP(S)."""

    def __init__(self, timeout_seconds: float = 60.0):
        self._timeout_seconds = timeout_seconds
        self._local_adapter = LocalAdapter()

    def fetch(
        self,
        url: str,
        text_column: str = "text",
        max_samples: int | None = None,
    ) -> list[dict[str, Any]]:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".txt", ".csv", ".json", ".jsonl"}:
            raise ValueError(f"Unsupported URL seed file type: {suffix or '<none>'}")

        logger.info("url_adapter.fetching", url=url, max_samples=max_samples)
        response = httpx.get(url, timeout=self._timeout_seconds, follow_redirects=True)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", delete=False) as f:
            f.write(response.text)
            temp_path = Path(f.name)

        try:
            records = self._local_adapter.fetch(
                local_path=temp_path,
                text_column=text_column,
                max_samples=max_samples,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        for record in records:
            metadata = dict(record.get("metadata") or {})
            metadata.setdefault("source_url", url)
            record["metadata"] = metadata

        logger.info("url_adapter.fetched", url=url, records=len(records))
        return records
