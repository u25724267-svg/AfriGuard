"""
AfriGuard Pydantic schemas — Annotation
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AnnotationDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    FLAG = "flag"       # Needs further discussion
    ESCALATE = "escalate"  # Send to senior reviewer


class HarmLabel(str, Enum):
    H01 = "H01"
    H02 = "H02"
    H03 = "H03"
    H04 = "H04"
    H05 = "H05"
    H06 = "H06"
    H07 = "H07"
    H08 = "H08"
    H09 = "H09"
    H10 = "H10"
    H11 = "H11"
    NOT_HARMFUL = "not_harmful"
    UNCLEAR = "unclear"


class SeverityLabel(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    NOT_APPLICABLE = "N/A"


class Annotation(BaseModel):
    """A human review decision on a candidate response."""

    id: str = Field(description="UUID")
    candidate_id: str = Field(description="ID of the reviewed CandidateResponse")
    prompt_id: str = Field(description="ID of the parent GeneratedPrompt")

    # Reviewer info (anonymized)
    annotator_id: str = Field(
        description="Hashed annotator identifier (language-based, e.g. hash('reviewer_hausa'))"
    )
    language: str = Field(description="Language reviewed")

    # Review decisions
    decision: AnnotationDecision = Field(description="The annotator's primary decision")
    harm_label: HarmLabel | None = Field(
        default=None,
        description="Annotator's harm category label (may correct model label)",
    )
    severity_label: SeverityLabel | None = Field(
        default=None, description="Annotator's severity assessment"
    )

    # Preference ranking (for preference-pair creation)
    # When multiple candidates exist for a prompt, rank them 1=best, 2=next, etc.
    preference_rank: int | None = Field(
        default=None,
        ge=1,
        description="Rank among candidates for this prompt (1 = most preferred)",
    )

    # Free text
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional annotator notes or corrections",
    )
    suggested_edit: str | None = Field(
        default=None,
        description="Corrected response text if annotator suggests an edit",
    )

    # Escalation
    is_escalated: bool = Field(default=False)
    escalation_reason: str | None = Field(default=None)

    created_at: datetime = Field(description="Annotation timestamp")
    updated_at: datetime | None = Field(default=None)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        use_enum_values = True
