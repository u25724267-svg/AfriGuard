"""
AfriGuard Pydantic schemas — CandidateResponse
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResponseType(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    AMBIGUOUS = "ambiguous"


class CandidateStatus(str, Enum):
    RAW = "raw"
    PASSED_FILTER = "passed_filter"
    FILTERED_LANGUAGE = "filtered_language"
    FILTERED_QUALITY = "filtered_quality"
    FILTERED_SIMILARITY = "filtered_similarity"
    FILTERED_DUPLICATE = "filtered_duplicate"
    SAMPLED_FOR_REVIEW = "sampled_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class CandidateResponse(BaseModel):
    """A single candidate response generated for a prompt."""

    id: str = Field(description="UUID")
    prompt_id: str = Field(description="ID of the parent GeneratedPrompt")
    language: str = Field(description="Target language name")
    language_code: str = Field(description="ISO language code")
    harm_category: str = Field(description="Harm category ID")
    severity: str = Field(description="Severity level")
    candidate_index: int = Field(
        description="Index within the batch of candidates for this prompt (0-indexed)"
    )

    # Content
    response_text: str = Field(description="The generated response text")
    response_type: ResponseType = Field(
        description="Whether this response models a safe or unsafe reply"
    )

    # Filter scores (None = not yet computed)
    detected_language: str | None = Field(
        default=None, description="Language detected by the language detector"
    )
    language_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence of language detection (1.0 = certain match)",
    )
    quality_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Composite quality score (length, coherence, relevance)",
    )
    similarity_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Max cosine similarity to other candidates in this batch",
    )

    status: CandidateStatus = Field(default=CandidateStatus.RAW)
    filter_reason: str | None = Field(
        default=None, description="Reason for filtering, if applicable"
    )

    # Generation metadata
    model_used: str = Field(description="Model that generated this response")
    generation_params: dict[str, Any] = Field(default_factory=dict)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)

    created_at: datetime = Field(description="Generation timestamp")
    run_id: str = Field(description="Pipeline run ID")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        use_enum_values = True
