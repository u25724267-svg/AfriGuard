"""Unit tests for configurable prompt templates."""

from src.prompt_construction.prompt_builder import PromptBuilder
from src.prompt_construction.prompt_template_loader import load_prompt_templates


def test_prompt_templates_load_from_config():
    templates = load_prompt_templates()

    assert templates.version == "1.0.0"
    assert "MODERATE" in templates.severity_frame("S2")
    assert "{language_instruction}" in templates.prompt_system_template
    assert "safe" in templates.response_role_instructions
    assert "unsafe" in templates.response_role_instructions


def test_prompt_builder_uses_configured_prompt_generation_template():
    builder = PromptBuilder()

    prompt = builder.build_system_prompt(
        language="shona",
        harm_category="H03",
        severity="S2",
        seed_context="Muenzaniso wechinyorwa cheShona.",
        entity_string="Names: Tendai, Rudo | Place: Harare | Org: Musasa Project",
    )

    assert "## Target Language" in prompt
    assert "## Generation Instructions" in prompt
    assert "MODERATE" in prompt
    assert "Muenzaniso wechinyorwa cheShona." in prompt
    assert builder.template_version == "1.0.0"


def test_prompt_builder_uses_configured_user_message_template():
    message = PromptBuilder().build_prompt_user_message(
        language="shona",
        harm_category="H03",
        severity="S2",
    )

    assert "Generate a S2 severity user prompt in shona" in message
    assert "Privacy Violations" in message


def test_prompt_builder_uses_configured_response_template():
    safe_prompt = PromptBuilder().build_response_system_prompt(
        language="shona",
        harm_category="H03",
        severity="S2",
        response_type="safe",
    )
    unsafe_prompt = PromptBuilder().build_response_system_prompt(
        language="shona",
        harm_category="H03",
        severity="S2",
        response_type="unsafe",
    )

    assert "responsible, helpful AI assistant" in safe_prompt
    assert "poorly-aligned AI system" in unsafe_prompt
    assert "Cyber and Data Protection Act" in safe_prompt
