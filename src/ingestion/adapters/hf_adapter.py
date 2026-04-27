"""
AfriGuard — Ingestion: HuggingFace dataset adapter.

Fetches datasets from HuggingFace Hub and returns raw records
as a list of dicts with standardized keys.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from src.config.env import load_project_env

load_project_env()
logger = structlog.get_logger(__name__)


class HFAdapter:
    """
    Adapter for fetching datasets from HuggingFace Hub via the `datasets` library.
    """

    def __init__(self, hf_token: str | None = None):
        self.hf_token = hf_token or os.environ.get("HF_TOKEN") or None

    def fetch(
        self,
        hf_path: str,
        hf_config: str | None = None,
        split: str = "train",
        text_column: str = "text",
        is_token_list: bool = False,
        max_samples: int | None = None,
        language_filter: str | None = None,
        language_column: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Download and return records from a HuggingFace dataset.

        Args:
            hf_path:         HuggingFace dataset path (e.g. 'masakhane/afrisenti')
            hf_config:       Optional dataset config/name for multilingual datasets
            split:           Dataset split to use
            text_column:     Column containing the primary text
            is_token_list:   If True, join token lists into space-separated strings
            max_samples:     If set, return only this many records (sampled from head)
            language_filter: If set, filter rows by this language name (exact match)
            language_column: Column to filter on when language_filter is set

        Returns:
            List of record dicts, each containing at least 'text' and 'metadata'.
        """
        try:
            from datasets import load_dataset  # lazy import to avoid slow startup
        except ImportError:
            raise ImportError("Install the 'datasets' package: pip install datasets")

        logger.info(
            "hf_adapter.fetching",
            path=hf_path,
            config=hf_config,
            split=split,
            max_samples=max_samples,
        )

        try:
            load_kwargs: dict[str, Any] = {"split": split}
            if self.hf_token:
                load_kwargs["token"] = self.hf_token

            if hf_config:
                ds = load_dataset(hf_path, hf_config, **load_kwargs)
            else:
                ds = load_dataset(hf_path, **load_kwargs)
        except Exception as e:
            logger.error("hf_adapter.load_failed", path=hf_path, error=str(e))
            raise

        # Apply language filter if specified
        if language_filter and language_column and language_column in ds.column_names:
            ds = ds.filter(lambda row: str(row[language_column]).lower() == language_filter.lower())
            logger.info("hf_adapter.language_filtered", remaining=len(ds), language=language_filter)

        if max_samples and len(ds) > max_samples:
            ds = ds.select(range(max_samples))

        records = []
        for row in ds:
            # Extract text
            if text_column not in row:
                logger.warning("hf_adapter.missing_column", column=text_column, available=list(row.keys()))
                continue

            raw_text = row[text_column]

            if is_token_list:
                if isinstance(raw_text, list):
                    text = " ".join(str(t) for t in raw_text if t)
                else:
                    text = str(raw_text)
            else:
                text = str(raw_text) if raw_text is not None else ""

            text = text.strip()
            if not text:
                continue

            # Build metadata from remaining columns
            metadata = {k: v for k, v in row.items() if k != text_column}

            records.append({"text": text, "metadata": metadata})

        logger.info("hf_adapter.fetched", path=hf_path, records=len(records))
        return records
