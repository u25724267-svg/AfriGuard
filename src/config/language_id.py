"""Config loader for local language-identification policy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.config.languages import list_language_names


_DEFAULT_LANGUAGE_ID_PATH = Path(__file__).resolve().parents[2] / "configs" / "language_id.yaml"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class GlotLIDConfig:
    enabled: bool
    model_path: str | None
    model_env_var: str
    top_k: int
    fallback_to_legacy: bool
    fail_on_missing_model: bool

    @property
    def resolved_model_path(self) -> str | None:
        env_value = os.environ.get(self.model_env_var)
        return env_value or self.model_path


@dataclass(frozen=True)
class LanguageIdThresholds:
    default: float
    short_text: float
    short_text_tokens: int
    contaminant_warning: float
    code_switch_margin: float
    related_label_multiplier: float
    mismatch_multiplier: float


@dataclass(frozen=True)
class LanguageIdTextConfig:
    min_chars: int
    min_tokens_for_confident_auto_pass: int
    short_text_policy: str


@dataclass(frozen=True)
class LanguageIdEntry:
    name: str
    glotlid_labels: tuple[str, ...]
    accepted_labels: tuple[str, ...]
    related_labels: tuple[str, ...]
    contaminant_labels: tuple[str, ...]
    threshold: float | None
    short_text_threshold: float | None
    min_chars: int | None
    review_required: bool
    notes: str

    @property
    def accepted_label_set(self) -> set[str]:
        return set(self.glotlid_labels) | set(self.accepted_labels)

    @property
    def related_label_set(self) -> set[str]:
        return set(self.related_labels)

    @property
    def contaminant_label_set(self) -> set[str]:
        return set(self.contaminant_labels)


@dataclass(frozen=True)
class LanguageIdConfig:
    glotlid: GlotLIDConfig
    thresholds: LanguageIdThresholds
    text: LanguageIdTextConfig
    global_contaminants: tuple[str, ...]
    languages: dict[str, LanguageIdEntry]
    path: Path

    def get_language(self, language: str) -> LanguageIdEntry | None:
        return self.languages.get(language.strip().lower())

    def threshold_for(self, language: str, token_count: int) -> float:
        entry = self.get_language(language)
        threshold = entry.threshold if entry and entry.threshold is not None else self.thresholds.default
        if (
            token_count < self.thresholds.short_text_tokens
            and self.text.short_text_policy == "raise_threshold"
        ):
            short_threshold = (
                entry.short_text_threshold
                if entry and entry.short_text_threshold is not None
                else self.thresholds.short_text
            )
            threshold = max(threshold, short_threshold)
        return threshold

    def min_chars_for(self, language: str) -> int:
        entry = self.get_language(language)
        if entry and entry.min_chars is not None:
            return entry.min_chars
        return self.text.min_chars


def _entry_from_raw(raw: dict[str, Any], global_contaminants: tuple[str, ...]) -> LanguageIdEntry:
    name = str(raw["name"]).strip().lower()
    contaminant_labels = tuple(dict.fromkeys((*global_contaminants, *_tuple(raw.get("contaminant_labels")))))
    threshold = raw.get("threshold")
    short_text_threshold = raw.get("short_text_threshold")
    min_chars = raw.get("min_chars")

    return LanguageIdEntry(
        name=name,
        glotlid_labels=_tuple(raw.get("glotlid_labels")),
        accepted_labels=_tuple(raw.get("accepted_labels")),
        related_labels=_tuple(raw.get("related_labels")),
        contaminant_labels=contaminant_labels,
        threshold=float(threshold) if threshold is not None else None,
        short_text_threshold=float(short_text_threshold) if short_text_threshold is not None else None,
        min_chars=int(min_chars) if min_chars is not None else None,
        review_required=bool(raw.get("review_required", True)),
        notes=str(raw.get("notes", "") or ""),
    )


@lru_cache(maxsize=1)
def load_language_id_config(
    language_id_path: str | Path = _DEFAULT_LANGUAGE_ID_PATH,
) -> LanguageIdConfig:
    path = Path(language_id_path)
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    glotlid = data.get("glotlid", {})
    thresholds = data.get("thresholds", {})
    text = data.get("text", {})
    contaminants = data.get("contaminants", {})
    global_contaminants = _tuple(contaminants.get("global", []))
    entries = [
        _entry_from_raw(row, global_contaminants)
        for row in data.get("languages", [])
        if row.get("name")
    ]

    return LanguageIdConfig(
        glotlid=GlotLIDConfig(
            enabled=_env_bool("GLOTLID_ENABLED", bool(glotlid.get("enabled", True))),
            model_path=glotlid.get("model_path"),
            model_env_var=str(glotlid.get("model_env_var", "GLOTLID_MODEL_PATH")),
            top_k=_env_int("GLOTLID_TOP_K", int(glotlid.get("top_k", 5))),
            fallback_to_legacy=_env_bool(
                "GLOTLID_FALLBACK_TO_LEGACY",
                bool(glotlid.get("fallback_to_legacy", True)),
            ),
            fail_on_missing_model=_env_bool(
                "GLOTLID_FAIL_ON_MISSING_MODEL",
                bool(glotlid.get("fail_on_missing_model", False)),
            ),
        ),
        thresholds=LanguageIdThresholds(
            default=_env_float("GLOTLID_DEFAULT_THRESHOLD", float(thresholds.get("default", 0.60))),
            short_text=_env_float(
                "GLOTLID_SHORT_TEXT_THRESHOLD",
                float(thresholds.get("short_text", 0.72)),
            ),
            short_text_tokens=_env_int(
                "GLOTLID_SHORT_TEXT_TOKENS",
                int(thresholds.get("short_text_tokens", 20)),
            ),
            contaminant_warning=float(thresholds.get("contaminant_warning", 0.35)),
            code_switch_margin=float(thresholds.get("code_switch_margin", 0.20)),
            related_label_multiplier=float(thresholds.get("related_label_multiplier", 0.65)),
            mismatch_multiplier=float(thresholds.get("mismatch_multiplier", 0.10)),
        ),
        text=LanguageIdTextConfig(
            min_chars=_env_int("LANGUAGE_ID_MIN_CHARS", int(text.get("min_chars", 10))),
            min_tokens_for_confident_auto_pass=int(
                text.get("min_tokens_for_confident_auto_pass", 20)
            ),
            short_text_policy=str(text.get("short_text_policy", "raise_threshold")),
        ),
        global_contaminants=global_contaminants,
        languages={entry.name: entry for entry in entries},
        path=path,
    )


def audit_language_id_config(config: LanguageIdConfig | None = None) -> dict[str, list[str]]:
    config = config or load_language_id_config()
    supported = set(list_language_names())
    configured = set(config.languages)
    missing_labels = sorted(
        name for name, entry in config.languages.items() if not entry.accepted_label_set
    )
    return {
        "missing_supported_languages": sorted(supported - configured),
        "unknown_configured_languages": sorted(configured - supported),
        "missing_accepted_labels": missing_labels,
    }
