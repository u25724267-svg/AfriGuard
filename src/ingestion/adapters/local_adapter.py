"""
AfriGuard — Ingestion: local file adapter.

Reads seed documents from local text, JSON, or JSONL files.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LocalAdapter:
    """
    Reads seed data from local files.

    Supported formats:
      - .txt   — one document per file
      - .csv   — one record per row
      - .json  — list of objects or a single object
      - .jsonl — one JSON object per line
    """

    def fetch(
        self,
        local_path: str | Path,
        text_column: str = "text",
        max_samples: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Load records from a local file.

        Returns:
            List of dicts with at least 'text' and 'metadata' keys.
        """
        path = Path(local_path)
        if not path.exists():
            logger.warning("local_adapter.file_not_found", path=str(path))
            return []

        suffix = path.suffix.lower()

        if suffix == ".txt":
            records = self._load_txt(path)
        elif suffix == ".csv":
            records = self._load_csv(path, text_column)
        elif suffix == ".json":
            records = self._load_json(path, text_column)
        elif suffix == ".jsonl":
            records = self._load_jsonl(path, text_column)
        else:
            logger.warning("local_adapter.unsupported_format", suffix=suffix, path=str(path))
            return []

        if max_samples and len(records) > max_samples:
            records = records[:max_samples]

        logger.info("local_adapter.loaded", path=str(path), records=len(records))
        return records

    def _load_txt(self, path: Path) -> list[dict[str, Any]]:
        """Load a plain text file as a single document."""
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [{"text": text, "metadata": {"filename": path.name}}]

    def _load_csv(self, path: Path, text_column: str) -> list[dict[str, Any]]:
        """Load a CSV file with one text record per row."""
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return self._normalize_records(list(reader), text_column)

    def _load_json(self, path: Path, text_column: str) -> list[dict[str, Any]]:
        """Load a JSON file (list of objects or single object)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return self._normalize_records(data, text_column)
        elif isinstance(data, dict):
            return self._normalize_records([data], text_column)
        else:
            logger.warning("local_adapter.unexpected_json_shape", path=str(path))
            return []

    def _load_jsonl(self, path: Path, text_column: str) -> list[dict[str, Any]]:
        """Load a JSONL file (one JSON object per line)."""
        records_raw = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records_raw.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("local_adapter.json_parse_error", error=str(e))
        return self._normalize_records(records_raw, text_column)

    def _normalize_records(
        self, records_raw: list[dict[str, Any]], text_column: str
    ) -> list[dict[str, Any]]:
        """Extract text and metadata from raw records."""
        out = []
        for row in records_raw:
            if isinstance(row, str):
                text = row
                metadata: dict[str, Any] = {}
            elif isinstance(row, dict):
                text = self._extract_text(row, text_column)
                metadata = {k: v for k, v in row.items() if k != text_column}
            else:
                continue
            if text:
                out.append({"text": text, "metadata": metadata})
        return out

    def _extract_text(self, row: dict[str, Any], text_column: str) -> str:
        """Extract primary text with common dataset-column fallbacks."""
        fallbacks = (text_column, "text", "message", "utterance", "normalized", "sentence")
        for column in fallbacks:
            value = row.get(column)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
