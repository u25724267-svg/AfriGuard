"""
AfriGuard - Prompt Construction: PromptBuilder

Renders configurable prompt templates for prompt and response generation.
The frequently tuned wording lives in configs/prompt_templates/prompt_templates.yaml;
this module supplies runtime context such as language instructions, taxonomy,
legal grounding, cultural entities, and seed excerpts.
"""

from __future__ import annotations

import structlog

from src.config.languages import get_language_config
from src.prompt_construction.legal_grounder import LegalGrounder
from src.prompt_construction.prompt_template_loader import (
    PromptTemplateConfig,
    load_prompt_templates,
)
from src.taxonomy.entity_sampler import EntitySampler
from src.taxonomy.harm_registry import HarmRegistry, get_registry

logger = structlog.get_logger(__name__)


class PromptBuilder:
    """
    Assembles system prompts and user messages for LLM generation.

    Prompt wording is loaded from YAML so researchers can tune generation
    behavior without changing Python code.
    """

    def __init__(
        self,
        registry: HarmRegistry | None = None,
        entity_sampler: EntitySampler | None = None,
        legal_grounder: LegalGrounder | None = None,
        template_config: PromptTemplateConfig | None = None,
    ):
        self._registry = registry or get_registry()
        self._entity_sampler = entity_sampler or EntitySampler()
        self._legal_grounder = legal_grounder or LegalGrounder(self._registry)
        self._templates = template_config or load_prompt_templates()

    @property
    def template_version(self) -> str:
        return self._templates.version

    def build_system_prompt(
        self,
        language: str,
        harm_category: str,
        severity: str,
        seed_context: str = "",
        entity_string: str | None = None,
    ) -> str:
        """
        Assemble the full system prompt for prompt generation.
        """
        cat = self._registry.get_category(harm_category)

        try:
            lang_instruction = get_language_config(language).prompt_instruction
        except KeyError:
            lang_instruction = f"Write the user prompt ENTIRELY in {language}. Do NOT use English."

        legal_context = self._legal_grounder.get_legal_context(language, harm_category)
        cultural_notes = self._registry.get_cultural_notes(harm_category, language)

        if entity_string is None:
            entity_string = self._entity_sampler.get_entity_string(language)

        subcats = ", ".join(cat.subcategories[:5]) if cat.subcategories else "general"

        return self._templates.prompt_system_template.format(
            language_instruction=lang_instruction,
            harm_category_id=harm_category,
            harm_category_name=cat.name,
            harm_category_description=cat.description.strip(),
            subcategories=subcats,
            severity_frame=self._templates.severity_frame(severity),
            legal_context=legal_context or "No specific legal context available.",
            cultural_notes=cultural_notes or "Follow general cultural norms for this language community.",
            entity_string=entity_string,
            seed_context=seed_context or "No seed context available for this language.",
            language=language,
            severity=severity,
        )

    def build_prompt_user_message(
        self,
        language: str,
        harm_category: str,
        severity: str,
    ) -> str:
        """Build the user message that asks the LLM to generate a prompt."""
        cat = self._registry.get_category(harm_category)
        return self._templates.prompt_user_message_template.format(
            language=language,
            harm_category_id=harm_category,
            harm_category_name=cat.name,
            severity=severity,
        )

    def build_pku_adaptation_system_prompt(
        self,
        language: str,
        harm_category: str,
        severity: str,
        source_prompt: str,
        seed_context: str = "",
        entity_string: str | None = None,
    ) -> str:
        """Assemble the system prompt for adapting a PKU source prompt."""
        cat = self._registry.get_category(harm_category)

        try:
            lang_instruction = get_language_config(language).prompt_instruction
        except KeyError:
            lang_instruction = f"Write the user prompt ENTIRELY in {language}. Do NOT use English."

        legal_context = self._legal_grounder.get_legal_context(language, harm_category)
        cultural_notes = self._registry.get_cultural_notes(harm_category, language)

        if entity_string is None:
            entity_string = self._entity_sampler.get_entity_string(language)

        subcats = ", ".join(cat.subcategories[:5]) if cat.subcategories else "general"

        return self._templates.pku_adaptation_system_template.format(
            language_instruction=lang_instruction,
            harm_category_id=harm_category,
            harm_category_name=cat.name,
            harm_category_description=cat.description.strip(),
            subcategories=subcats,
            severity_frame=self._templates.severity_frame(severity),
            legal_context=legal_context or "No specific legal context available.",
            cultural_notes=cultural_notes or "Follow general cultural norms for this language community.",
            entity_string=entity_string,
            seed_context=seed_context or "No seed context available for this language.",
            source_prompt=source_prompt,
            language=language,
            severity=severity,
        )

    def build_pku_adaptation_user_message(
        self,
        language: str,
        harm_category: str,
        severity: str,
        source_prompt: str,
    ) -> str:
        """Build the user message that asks the LLM to adapt a source prompt."""
        cat = self._registry.get_category(harm_category)
        return self._templates.pku_adaptation_user_message_template.format(
            language=language,
            harm_category_id=harm_category,
            harm_category_name=cat.name,
            severity=severity,
            source_prompt=source_prompt,
        )

    def build_response_system_prompt(
        self,
        language: str,
        harm_category: str,
        severity: str,
        response_type: str,
    ) -> str:
        """
        Build the system prompt for generating a response to a user prompt.
        """
        cat = self._registry.get_category(harm_category)
        legal_context = self._legal_grounder.get_legal_context(language, harm_category)

        try:
            lang_instruction = get_language_config(language).response_instruction
        except KeyError:
            lang_instruction = f"Respond ENTIRELY in {language}. Do NOT use English."

        return self._templates.response_system_template.format(
            language_instruction=lang_instruction,
            harm_category_id=harm_category,
            harm_category_name=cat.name,
            legal_context=legal_context,
            role_instruction=self._templates.response_role_instruction(response_type),
            response_type=response_type,
            language=language,
            severity=severity,
        )

    def get_entities_injected(self, language: str) -> list[str]:
        """Return a list of entity strings sampled for this language."""
        entities = self._entity_sampler.sample_all(language)
        return entities["names"] + entities["places"] + entities["organizations"]

    def get_legal_context(self, language: str, harm_category: str) -> str:
        """Return the legal context injected into prompts for provenance."""
        return self._legal_grounder.get_legal_context(language, harm_category)
