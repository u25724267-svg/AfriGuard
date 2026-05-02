"""Central seed-context injection policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_SEED_CONTEXT_PATH = Path(__file__).resolve().parents[2] / "configs" / "seed_context.yaml"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class SeedContextConfig:
    n_seeds: int
    max_excerpt_chars: int
    exact_match_pool_multiplier: int
    language_fallback_pool_multiplier: int
    fallback_to_language: bool
    shuffle: bool
    enabled: bool


@lru_cache(maxsize=1)
def load_seed_context_config(
    config_path: str | Path = _DEFAULT_SEED_CONTEXT_PATH,
) -> SeedContextConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return SeedContextConfig(
        n_seeds=_env_int("SEED_CONTEXT_N_SEEDS", int(data.get("n_seeds", 5))),
        max_excerpt_chars=_env_int(
            "SEED_CONTEXT_MAX_EXCERPT_CHARS",
            int(data.get("max_excerpt_chars", 400)),
        ),
        exact_match_pool_multiplier=_env_int(
            "SEED_CONTEXT_EXACT_MATCH_POOL_MULTIPLIER",
            int(data.get("exact_match_pool_multiplier", 5)),
        ),
        language_fallback_pool_multiplier=_env_int(
            "SEED_CONTEXT_LANGUAGE_FALLBACK_POOL_MULTIPLIER",
            int(data.get("language_fallback_pool_multiplier", 3)),
        ),
        fallback_to_language=_env_bool(
            "SEED_CONTEXT_FALLBACK_TO_LANGUAGE",
            bool(data.get("fallback_to_language", True)),
        ),
        shuffle=_env_bool("SEED_CONTEXT_SHUFFLE", bool(data.get("shuffle", True))),
        enabled=_env_bool("SEED_CONTEXT_ENABLED", bool(data.get("enabled", True))),
    )
