"""Load configurable prompt templates for AfriGuard generation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "prompt_templates" / "prompt_templates.yaml"
)


@dataclass(frozen=True)
class PromptTemplateConfig:
    version: str
    severity_frames: dict[str, str]
    prompt_system_template: str
    prompt_user_message_template: str
    response_system_template: str
    response_role_instructions: dict[str, str]

    def severity_frame(self, severity: str) -> str:
        return self.severity_frames.get(severity, self.severity_frames.get("S2", ""))

    def response_role_instruction(self, response_type: str) -> str:
        return self.response_role_instructions.get(
            response_type,
            self.response_role_instructions.get("safe", ""),
        )


def _required(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None:
        raise ValueError(f"Missing required prompt template key: {key}")
    return value


@lru_cache(maxsize=1)
def load_prompt_templates(
    template_path: str | Path = _DEFAULT_TEMPLATE_PATH,
) -> PromptTemplateConfig:
    with open(template_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    prompt_generation = _required(data, "prompt_generation")
    response_generation = _required(data, "response_generation")

    return PromptTemplateConfig(
        version=str(data.get("version", "1.0.0")),
        severity_frames=dict(_required(data, "severity_frames")),
        prompt_system_template=str(_required(prompt_generation, "system_template")),
        prompt_user_message_template=str(_required(prompt_generation, "user_message_template")),
        response_system_template=str(_required(response_generation, "system_template")),
        response_role_instructions=dict(_required(response_generation, "role_instructions")),
    )
