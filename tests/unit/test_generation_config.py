"""Unit tests for generation policy configuration."""

import pytest

from src.config.generation import CandidateMixConfig, load_generation_config


def test_generation_config_loads_default_candidate_mix():
    config = load_generation_config()

    assert config.default_model == "gpt-4o"
    assert config.candidates_per_prompt == 4
    assert config.prompt_generation.to_dict() == {
        "temperature": 0.9,
        "max_tokens": 256,
    }
    assert config.response_generation.to_dict() == {
        "temperature": 0.9,
        "max_tokens": 1024,
    }
    assert config.candidate_mix.safe_fraction == 0.50
    assert config.candidate_mix.unsafe_fraction == 0.50
    assert config.candidate_mix.response_type_counts(4) == (2, 2)


def test_env_override_for_safe_fraction(monkeypatch):
    monkeypatch.setenv("GENERATION_SAFE_FRACTION", "0.25")
    load_generation_config.cache_clear()

    try:
        config = load_generation_config()
        assert config.candidate_mix.response_type_counts(4) == (1, 3)
    finally:
        load_generation_config.cache_clear()


def test_invalid_safe_fraction_raises(monkeypatch):
    monkeypatch.setenv("GENERATION_SAFE_FRACTION", "1.5")
    load_generation_config.cache_clear()

    try:
        with pytest.raises(ValueError):
            load_generation_config()
    finally:
        load_generation_config.cache_clear()


def test_env_override_for_generation_parameters(monkeypatch):
    monkeypatch.setenv("PIPELINE_DEFAULT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("PIPELINE_CANDIDATES_PER_PROMPT", "6")
    monkeypatch.setenv("GENERATION_PROMPT_MAX_TOKENS", "128")
    monkeypatch.setenv("GENERATION_RESPONSE_TEMPERATURE", "0.4")
    load_generation_config.cache_clear()

    try:
        config = load_generation_config()
        assert config.default_model == "gpt-4o-mini"
        assert config.candidates_per_prompt == 6
        assert config.prompt_generation.max_tokens == 128
        assert config.response_generation.temperature == 0.4
    finally:
        load_generation_config.cache_clear()


def test_candidate_mix_rejects_negative_candidate_count():
    with pytest.raises(ValueError):
        CandidateMixConfig(safe_fraction=0.50).response_type_counts(-1)
