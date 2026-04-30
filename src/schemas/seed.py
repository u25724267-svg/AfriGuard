"""
AfriGuard Pydantic schemas — SeedDocument
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

from src.config.languages import is_supported_language, list_language_names


class SeedDocument(BaseModel):
    """A single seed document ingested from an Afrocentric corpus."""

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    id: str = Field(description="UUID for this seed document")
    source_id: str = Field(description="ID from seed_sources.yaml (e.g. 'afrisenti')")
    source_name: str = Field(description="Human-readable dataset name")
    source_split: str = Field(default="train", description="Dataset split used")
    language: str = Field(description="Language name (e.g. 'hausa')")
    language_code: str = Field(description="ISO language code (e.g. 'ha')")
    harm_domains: list[str] = Field(
        default_factory=list,
        description="Applicable harm category IDs (e.g. ['H01', 'H07'])",
    )
    text: str = Field(description="Normalized text content of the seed document")
    original_text: str = Field(description="Raw text before normalization")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary source-specific metadata"
    )
    license: str = Field(default="unknown", description="License of the source dataset")
    fetched_at: datetime = Field(description="When this document was ingested")
    provenance_hash: str = Field(
        description="SHA-256 of (source_id + original_text) for deduplication"
    )

    @model_validator(mode="before")
    @classmethod
    def compute_provenance_hash(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "provenance_hash" not in values or not values.get("provenance_hash"):
            source_id = values.get("source_id", "")
            original_text = values.get("original_text", values.get("text", ""))
            raw = f"{source_id}::{original_text}"
            values["provenance_hash"] = hashlib.sha256(raw.encode()).hexdigest()
        return values

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        if not is_supported_language(v):
            allowed = set(list_language_names())
            raise ValueError(f"Language '{v}' not in supported set: {allowed}")
        return v

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        return v
