"""Unit tests for legal grounding policy configuration."""

from src.config.legal_grounding import (
    LegalGroundingConfig,
    load_legal_grounding_config,
)
from src.prompt_construction.legal_grounder import LegalGrounder


def _legal_config(**overrides):
    defaults = {
        "enabled": True,
        "include_embedded_summaries": True,
        "include_registry_references": True,
        "fallback_to_generic": True,
        "max_chars": 1200,
    }
    defaults.update(overrides)
    return LegalGroundingConfig(**defaults)


def test_legal_grounding_config_loads_defaults():
    config = load_legal_grounding_config()

    assert config.enabled is True
    assert config.include_embedded_summaries is True
    assert config.include_registry_references is True
    assert config.fallback_to_generic is True
    assert config.max_chars == 1200


def test_env_override_can_disable_legal_grounding(monkeypatch):
    monkeypatch.setenv("LEGAL_GROUNDING_ENABLED", "false")
    load_legal_grounding_config.cache_clear()

    try:
        assert load_legal_grounding_config().enabled is False
    finally:
        load_legal_grounding_config.cache_clear()


def test_legal_grounder_returns_empty_when_disabled():
    grounder = LegalGrounder(config=_legal_config(enabled=False))

    assert grounder.get_legal_context("shona", "H03") == ""


def test_legal_grounder_truncates_context():
    grounder = LegalGrounder(config=_legal_config(max_chars=30))

    context = grounder.get_legal_context("shona", "H03")

    assert len(context) <= 33
    assert context.endswith("...")
