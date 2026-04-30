"""Central language metadata registry for AfriGuard."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_LANGUAGES_PATH = Path(__file__).resolve().parents[2] / "configs" / "languages.yaml"


@dataclass(frozen=True)
class LanguageConfig:
    name: str
    display_name: str
    code: str
    iso_639_3: str
    region: str
    countries: tuple[str, ...]
    reviewer_id: str
    password_env: str
    default_password: str
    flag: str
    low_resource_detection: bool
    char_ngram_similarity: bool
    aliases: tuple[str, ...]
    prompt_instruction: str
    response_instruction: str


def _normalise_name(language: str) -> str:
    return language.strip().lower()


def _build_config(raw: dict[str, Any]) -> LanguageConfig:
    name = _normalise_name(raw["name"])
    aliases = {name, raw.get("code", ""), raw.get("iso_639_3", "")}
    aliases.update(str(alias).strip().lower() for alias in raw.get("aliases", []))
    aliases = {alias for alias in aliases if alias}

    return LanguageConfig(
        name=name,
        display_name=raw.get("display_name", name.replace("_", " ").title()),
        code=raw.get("code", name),
        iso_639_3=raw.get("iso_639_3", raw.get("code", name)),
        region=raw.get("region", ""),
        countries=tuple(raw.get("countries", [])),
        reviewer_id=raw.get("reviewer_id", f"reviewer_{name}"),
        password_env=raw.get("password_env", f"PASS_{name.upper()}"),
        default_password=raw.get("default_password", f"{name}_review_poc"),
        flag=raw.get("flag", ""),
        low_resource_detection=bool(raw.get("low_resource_detection", False)),
        char_ngram_similarity=bool(raw.get("char_ngram_similarity", False)),
        aliases=tuple(sorted(aliases)),
        prompt_instruction=raw.get(
            "prompt_instruction",
            f"Write the user prompt ENTIRELY in {name}. Do NOT use English.",
        ).strip(),
        response_instruction=raw.get(
            "response_instruction",
            f"Respond ENTIRELY in {name}. Do NOT use English.",
        ).strip(),
    )


@lru_cache(maxsize=1)
def load_language_configs(
    languages_path: str | Path = _DEFAULT_LANGUAGES_PATH,
) -> dict[str, LanguageConfig]:
    with open(languages_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    configs = [_build_config(row) for row in data.get("languages", [])]
    return {config.name: config for config in configs}


def list_language_configs() -> list[LanguageConfig]:
    return list(load_language_configs().values())


def list_language_names() -> list[str]:
    return list(load_language_configs().keys())


def get_language_config(language: str) -> LanguageConfig:
    name = _normalise_name(language)
    configs = load_language_configs()
    if name in configs:
        return configs[name]

    for config in configs.values():
        if name in config.aliases:
            return config

    raise KeyError(f"Unsupported language: {language}")


def is_supported_language(language: str) -> bool:
    try:
        get_language_config(language)
        return True
    except KeyError:
        return False


def get_language_code(language: str) -> str:
    return get_language_config(language).code


def get_language_codes_map() -> dict[str, set[str]]:
    return {
        config.name: {config.code, config.iso_639_3}
        for config in list_language_configs()
    }


def get_language_aliases_map() -> dict[str, set[str]]:
    return {
        config.name: set(config.aliases)
        for config in list_language_configs()
    }


def get_low_resource_languages() -> set[str]:
    return {
        config.name
        for config in list_language_configs()
        if config.low_resource_detection
    }


def get_char_ngram_similarity_languages() -> set[str]:
    return {
        config.name
        for config in list_language_configs()
        if config.char_ngram_similarity
    }


def get_language_reviewer_map() -> dict[str, str]:
    return {
        config.name: config.reviewer_id
        for config in list_language_configs()
    }


def get_reviewer_language(reviewer_id: str) -> str | None:
    for config in list_language_configs():
        if config.reviewer_id == reviewer_id:
            return config.name
    return None


def get_reviewer_accounts() -> list[dict[str, str]]:
    return [
        {
            "reviewer_id": config.reviewer_id,
            "language": config.name,
            "display_name": config.display_name,
            "password_env": config.password_env,
            "default_password": config.default_password,
            "flag": config.flag,
        }
        for config in list_language_configs()
    ]


def get_legal_countries(language: str) -> list[str]:
    return list(get_language_config(language).countries)
