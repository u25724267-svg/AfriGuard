"""Central dataset export policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_EXPORT_PATH = Path(__file__).resolve().parents[2] / "configs" / "export.yaml"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ExportConfig:
    write_native_jsonl: bool
    write_pku_style_jsonl: bool
    write_all_languages: bool
    write_dataset_card: bool
    native_item_types: tuple[str, ...]


@lru_cache(maxsize=1)
def load_export_config(config_path: str | Path = _DEFAULT_EXPORT_PATH) -> ExportConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return ExportConfig(
        write_native_jsonl=_env_bool(
            "EXPORT_WRITE_NATIVE_JSONL",
            bool(data.get("write_native_jsonl", True)),
        ),
        write_pku_style_jsonl=_env_bool(
            "EXPORT_WRITE_PKU_STYLE_JSONL",
            bool(data.get("write_pku_style_jsonl", True)),
        ),
        write_all_languages=_env_bool(
            "EXPORT_WRITE_ALL_LANGUAGES",
            bool(data.get("write_all_languages", True)),
        ),
        write_dataset_card=_env_bool(
            "EXPORT_WRITE_DATASET_CARD",
            bool(data.get("write_dataset_card", True)),
        ),
        native_item_types=tuple(
            data.get(
                "native_item_types",
                ["preference_pair", "qa_safe", "qa_unsafe", "classification"],
            )
        ),
    )
