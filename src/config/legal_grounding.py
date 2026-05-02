"""Central legal grounding policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_LEGAL_GROUNDING_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "legal_grounding.yaml"
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class LegalGroundingConfig:
    enabled: bool
    include_embedded_summaries: bool
    include_registry_references: bool
    fallback_to_generic: bool
    max_chars: int


@lru_cache(maxsize=1)
def load_legal_grounding_config(
    config_path: str | Path = _DEFAULT_LEGAL_GROUNDING_PATH,
) -> LegalGroundingConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return LegalGroundingConfig(
        enabled=_env_bool("LEGAL_GROUNDING_ENABLED", bool(data.get("enabled", True))),
        include_embedded_summaries=_env_bool(
            "LEGAL_GROUNDING_INCLUDE_SUMMARIES",
            bool(data.get("include_embedded_summaries", True)),
        ),
        include_registry_references=_env_bool(
            "LEGAL_GROUNDING_INCLUDE_REGISTRY_REFERENCES",
            bool(data.get("include_registry_references", True)),
        ),
        fallback_to_generic=_env_bool(
            "LEGAL_GROUNDING_FALLBACK_TO_GENERIC",
            bool(data.get("fallback_to_generic", True)),
        ),
        max_chars=_env_int("LEGAL_GROUNDING_MAX_CHARS", int(data.get("max_chars", 1200))),
    )
