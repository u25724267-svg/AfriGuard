"""
AfriGuard — Taxonomy: HarmRegistry

Loads and provides access to the Afrocentric harm taxonomy defined in
configs/harm_taxonomy.yaml. Supports severity calibration per language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_TAXONOMY_PATH = Path(__file__).parent.parent.parent / "configs" / "harm_taxonomy.yaml"


@dataclass
class SeverityLevel:
    code: str        # S1, S2, S3, S4
    name: str
    description: str
    review_required: bool
    auto_escalate: bool


@dataclass
class HarmCategory:
    id: str          # H01 ... H11
    name: str
    description: str
    subcategories: list[str]
    legal_references: list[dict[str, str]]
    cultural_notes: dict[str, str]
    severity_overrides: dict[str, Any]
    languages: list[str]


class HarmRegistry:
    """
    Loads the harm taxonomy from YAML and provides query methods.

    Usage:
        registry = HarmRegistry()
        category = registry.get_category("H01")
        severity = registry.get_severity("S2")
        all_cats = registry.list_categories()
    """

    def __init__(self, taxonomy_path: Path = _DEFAULT_TAXONOMY_PATH):
        self._path = taxonomy_path
        self._categories: dict[str, HarmCategory] = {}
        self._severity_levels: dict[str, SeverityLevel] = {}
        self._raw: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        logger.info("harm_registry.loading", path=str(self._path))
        with open(self._path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._raw = data

        for cat_id, cat_data in data.get("categories", {}).items():
            self._categories[cat_id] = HarmCategory(
                id=cat_id,
                name=cat_data["name"],
                description=cat_data.get("description", ""),
                subcategories=cat_data.get("subcategories", []),
                legal_references=cat_data.get("legal_references", []),
                cultural_notes=cat_data.get("cultural_notes", {}),
                severity_overrides=cat_data.get("severity_overrides", {}),
                languages=cat_data.get("languages", []),
            )

        for sev_code, sev_data in data.get("severity_levels", {}).items():
            self._severity_levels[sev_code] = SeverityLevel(
                code=sev_code,
                name=sev_data["name"],
                description=sev_data["description"],
                review_required=sev_data.get("review_required", True),
                auto_escalate=sev_data.get("auto_escalate", False),
            )

        logger.info(
            "harm_registry.loaded",
            categories=len(self._categories),
            severity_levels=len(self._severity_levels),
        )

    def get_category(self, category_id: str) -> HarmCategory:
        if category_id not in self._categories:
            raise KeyError(f"Unknown harm category: {category_id}")
        return self._categories[category_id]

    def get_severity(self, severity_code: str) -> SeverityLevel:
        if severity_code not in self._severity_levels:
            raise KeyError(f"Unknown severity level: {severity_code}")
        return self._severity_levels[severity_code]

    def list_categories(self) -> list[HarmCategory]:
        return list(self._categories.values())

    def list_category_ids(self) -> list[str]:
        return list(self._categories.keys())

    def list_severity_codes(self) -> list[str]:
        return list(self._severity_levels.keys())

    def get_legal_references(self, category_id: str, language: str) -> list[str]:
        """Return formatted legal references relevant to a language."""
        cat = self.get_category(category_id)
        # Map languages to countries
        lang_country_map = {
            "hausa": ["Nigeria"],
            "yoruba": ["Nigeria"],
            "sepedi": ["South Africa"],
            "northern_sotho": ["South Africa"],
            "chichewa": ["Malawi"],
            "yao": ["Malawi"],
            "shona": ["Zimbabwe"],
        }
        relevant_countries = lang_country_map.get(language.lower(), [])
        refs = []
        for ref in cat.legal_references:
            if not relevant_countries or ref.get("country") in relevant_countries:
                refs.append(f"{ref.get('country', '')}: {ref.get('law', '')}")
        return refs

    def get_cultural_notes(self, category_id: str, language: str) -> str:
        """Return cultural notes for a specific language, falling back to 'all'."""
        cat = self.get_category(category_id)
        notes = cat.cultural_notes
        return notes.get(language.lower(), notes.get("all", ""))

    def requires_review(self, severity_code: str) -> bool:
        return self.get_severity(severity_code).review_required

    def requires_escalation(self, severity_code: str) -> bool:
        return self.get_severity(severity_code).auto_escalate

    def get_subcategories(self, category_id: str) -> list[str]:
        return self.get_category(category_id).subcategories

    @property
    def version(self) -> str:
        return self._raw.get("version", "unknown")


# Module-level singleton
_registry: HarmRegistry | None = None


def get_registry(taxonomy_path: Path = _DEFAULT_TAXONOMY_PATH) -> HarmRegistry:
    """Return the module-level singleton HarmRegistry."""
    global _registry
    if _registry is None:
        _registry = HarmRegistry(taxonomy_path)
    return _registry
