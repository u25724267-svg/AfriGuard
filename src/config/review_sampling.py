"""Central review sampling policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_REVIEW_SAMPLING_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "review_sampling.yaml"
)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class ReviewSamplingConfig:
    n_per_language: int
    borderline_fraction: float
    borderline_margin: float


@lru_cache(maxsize=1)
def load_review_sampling_config(
    config_path: str | Path = _DEFAULT_REVIEW_SAMPLING_PATH,
) -> ReviewSamplingConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return ReviewSamplingConfig(
        n_per_language=_env_int(
            "REVIEW_SAMPLE_N_PER_LANGUAGE",
            int(data.get("n_per_language", 50)),
        ),
        borderline_fraction=_env_float(
            "REVIEW_SAMPLE_BORDERLINE_FRACTION",
            float(data.get("borderline_fraction", 0.20)),
        ),
        borderline_margin=_env_float(
            "REVIEW_SAMPLE_BORDERLINE_MARGIN",
            float(data.get("borderline_margin", 0.15)),
        ),
    )
