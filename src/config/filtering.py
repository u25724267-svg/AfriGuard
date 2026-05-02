"""Central filtering policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_FILTERING_PATH = Path(__file__).resolve().parents[2] / "configs" / "filtering.yaml"


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class LanguageDetectionConfig:
    min_text_chars: int
    library_accept_threshold: float
    default_threshold: float
    low_resource_threshold: float
    llm_failure_fallback_confidence: float


@dataclass(frozen=True)
class FilteringConfig:
    min_quality_score: float
    similarity_threshold: float
    deduplication_threshold: float
    language_detection: LanguageDetectionConfig


@lru_cache(maxsize=1)
def load_filtering_config(
    filtering_path: str | Path = _DEFAULT_FILTERING_PATH,
) -> FilteringConfig:
    with open(filtering_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    quality = data.get("quality", {})
    similarity = data.get("similarity", {})
    deduplication = data.get("deduplication", {})
    language = data.get("language_detection", {})

    return FilteringConfig(
        min_quality_score=_env_float(
            "PIPELINE_MIN_QUALITY_SCORE",
            float(quality.get("min_score", 0.60)),
        ),
        similarity_threshold=_env_float(
            "PIPELINE_SIMILARITY_THRESHOLD",
            float(similarity.get("threshold", 0.85)),
        ),
        deduplication_threshold=_env_float(
            "PIPELINE_DEDUPLICATION_THRESHOLD",
            float(deduplication.get("threshold", 0.70)),
        ),
        language_detection=LanguageDetectionConfig(
            min_text_chars=_env_int(
                "LANGUAGE_DETECTION_MIN_TEXT_CHARS",
                int(language.get("min_text_chars", 10)),
            ),
            library_accept_threshold=_env_float(
                "LANGUAGE_DETECTION_LIBRARY_ACCEPT_THRESHOLD",
                float(language.get("library_accept_threshold", 0.50)),
            ),
            default_threshold=_env_float(
                "LANGUAGE_DETECTION_DEFAULT_THRESHOLD",
                float(language.get("default_threshold", 0.40)),
            ),
            low_resource_threshold=_env_float(
                "LANGUAGE_DETECTION_LOW_RESOURCE_THRESHOLD",
                float(language.get("low_resource_threshold", 0.35)),
            ),
            llm_failure_fallback_confidence=_env_float(
                "LANGUAGE_DETECTION_LLM_FAILURE_CONFIDENCE",
                float(language.get("llm_failure_fallback_confidence", 0.40)),
            ),
        ),
    )
