"""Central generation policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_GENERATION_PATH = Path(__file__).resolve().parents[2] / "configs" / "generation.yaml"


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class CandidateMixConfig:
    safe_fraction: float

    @property
    def unsafe_fraction(self) -> float:
        return 1.0 - self.safe_fraction

    def response_type_counts(self, n_candidates: int) -> tuple[int, int]:
        if n_candidates < 0:
            raise ValueError("n_candidates must be non-negative")

        n_safe = int(n_candidates * self.safe_fraction)
        n_safe = max(0, min(n_candidates, n_safe))
        return n_safe, n_candidates - n_safe


@dataclass(frozen=True)
class GenerationParamsConfig:
    temperature: float
    max_tokens: int

    def to_dict(self) -> dict[str, int | float]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class GenerationConfig:
    default_model: str
    candidates_per_prompt: int
    prompt_generation: GenerationParamsConfig
    response_generation: GenerationParamsConfig
    candidate_mix: CandidateMixConfig


@lru_cache(maxsize=1)
def load_generation_config(
    config_path: str | Path = _DEFAULT_GENERATION_PATH,
) -> GenerationConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    prompt_generation = data.get("prompt_generation", {})
    response_generation = data.get("response_generation", {})
    candidate_mix = data.get("candidate_mix", {})
    safe_fraction = _env_float(
        "GENERATION_SAFE_FRACTION",
        float(candidate_mix.get("safe_fraction", 0.50)),
    )
    if not 0 <= safe_fraction <= 1:
        raise ValueError("GENERATION_SAFE_FRACTION must be between 0 and 1")

    return GenerationConfig(
        default_model=_env_str(
            "PIPELINE_DEFAULT_MODEL",
            str(data.get("default_model", "gpt-4o")),
        ),
        candidates_per_prompt=_env_int(
            "PIPELINE_CANDIDATES_PER_PROMPT",
            int(data.get("candidates_per_prompt", 4)),
        ),
        prompt_generation=GenerationParamsConfig(
            temperature=_env_float(
                "GENERATION_PROMPT_TEMPERATURE",
                float(prompt_generation.get("temperature", 0.9)),
            ),
            max_tokens=_env_int(
                "GENERATION_PROMPT_MAX_TOKENS",
                int(prompt_generation.get("max_tokens", 256)),
            ),
        ),
        response_generation=GenerationParamsConfig(
            temperature=_env_float(
                "GENERATION_RESPONSE_TEMPERATURE",
                float(response_generation.get("temperature", 0.9)),
            ),
            max_tokens=_env_int(
                "GENERATION_RESPONSE_MAX_TOKENS",
                int(response_generation.get("max_tokens", 1024)),
            ),
        ),
        candidate_mix=CandidateMixConfig(safe_fraction=safe_fraction),
    )
