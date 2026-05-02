"""Central reviewer UI configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_REVIEW_UI_PATH = Path(__file__).resolve().parents[2] / "configs" / "review_ui.yaml"


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class ReviewUIText:
    app_name: str
    login_title: str
    login_subtitle: str
    language_select_label: str
    language_select_placeholder: str
    sign_in_button: str
    invalid_login_error: str
    review_title: str
    review_brand: str
    stats_link_label: str
    logout_label: str
    annotations_completed_label: str
    queue_count_label: str
    prompt_group_count_label: str
    empty_title: str
    empty_body: str
    review_instructions: str
    candidate_heading: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewUIConfig:
    tasks_per_page: int
    text: ReviewUIText

    def template_context(self) -> dict[str, Any]:
        return {
            "tasks_per_page": self.tasks_per_page,
            **self.text.to_dict(),
        }


@lru_cache(maxsize=1)
def load_review_ui_config(
    config_path: str | Path = _DEFAULT_REVIEW_UI_PATH,
) -> ReviewUIConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    text = data.get("text", {})
    defaults = {
        "app_name": "AfriGuard",
        "login_title": "AfriGuard - Login",
        "login_subtitle": "Safety Alignment Review Portal",
        "language_select_label": "Language To Review",
        "language_select_placeholder": "Select your language",
        "sign_in_button": "Sign In",
        "invalid_login_error": "Invalid credentials. Please try again.",
        "review_title": "AfriGuard - Review Queue",
        "review_brand": "AfriGuard Review",
        "stats_link_label": "Stats",
        "logout_label": "Sign out",
        "annotations_completed_label": "Annotations completed",
        "queue_count_label": "Review items in queue",
        "prompt_group_count_label": "Prompt groups open",
        "empty_title": "All caught up!",
        "empty_body": (
            "No pending review tasks for your language. Check back after the next generation run."
        ),
        "review_instructions": (
            "Check language naturalness, cultural fit, harm label, severity, "
            "and whether the response should be approved, rejected, flagged, or escalated."
        ),
        "candidate_heading": "Candidate Responses - select decision for each",
    }
    defaults.update(text)

    return ReviewUIConfig(
        tasks_per_page=_env_int(
            "REVIEW_UI_TASKS_PER_PAGE",
            int(data.get("tasks_per_page", 10)),
        ),
        text=ReviewUIText(**defaults),
    )
