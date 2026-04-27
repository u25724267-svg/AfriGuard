"""
AfriGuard Pydantic schemas — DatasetItem
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    PREFERENCE_PAIR = "preference_pair"    # chosen / rejected pair for RLHF
    QA_SAFE = "qa_safe"                    # (prompt, safe_response) for SFT
    QA_UNSAFE = "qa_unsafe"               # (prompt, unsafe_response) for SFT
    CLASSIFICATION = "classification"      # (text, harm_label, severity) for moderation


class DatasetItem(BaseModel):
    """A finalized, human-reviewed dataset item ready for export."""

    id: str = Field(description="UUID")
    item_type: ItemType = Field(description="Format of this dataset item")
    language: str = Field(description="Language name")
    language_code: str = Field(description="ISO language code")
    harm_category: str = Field(description="Harm category ID")
    harm_category_name: str = Field(description="Human-readable harm category name")
    severity: str = Field(description="Severity level")

    # Core content
    prompt_id: str = Field(description="ID of the source GeneratedPrompt")
    prompt_text: str = Field(description="The user-facing prompt text")

    # Preference pair fields
    chosen_response_id: str | None = Field(default=None)
    chosen_response_text: str | None = Field(default=None)
    rejected_response_id: str | None = Field(default=None)
    rejected_response_text: str | None = Field(default=None)

    # QA fields
    response_id: str | None = Field(default=None)
    response_text: str | None = Field(default=None)

    # Classification fields
    classification_text: str | None = Field(
        default=None, description="Text to classify (may be prompt or response)"
    )
    harm_label: str | None = Field(default=None)
    severity_label: str | None = Field(default=None)

    # Provenance chain
    seed_document_ids: list[str] = Field(default_factory=list)
    prompt_template_id: str = Field(description="Template used to generate the prompt")
    annotator_ids: list[str] = Field(
        default_factory=list, description="Hashed annotator IDs who reviewed this item"
    )
    models_used: list[str] = Field(
        default_factory=list, description="All model IDs involved in creating this item"
    )

    # Dataset version
    dataset_version: str = Field(description="Semantic version tag of the dataset release")
    run_id: str = Field(description="Pipeline run ID")

    created_at: datetime = Field(description="Assembly timestamp")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        use_enum_values = True
