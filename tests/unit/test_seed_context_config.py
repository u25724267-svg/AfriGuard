"""Unit tests for seed-context injection policy configuration."""

from src.config.seed_context import SeedContextConfig, load_seed_context_config
from src.prompt_construction.seed_context_injector import SeedContextInjector


def _seed_config(**overrides):
    defaults = {
        "n_seeds": 5,
        "max_excerpt_chars": 400,
        "exact_match_pool_multiplier": 5,
        "language_fallback_pool_multiplier": 3,
        "fallback_to_language": True,
        "shuffle": True,
        "enabled": True,
    }
    defaults.update(overrides)
    return SeedContextConfig(**defaults)


def test_seed_context_config_loads_defaults():
    config = load_seed_context_config()

    assert config.n_seeds == 5
    assert config.max_excerpt_chars == 400
    assert config.exact_match_pool_multiplier == 5
    assert config.language_fallback_pool_multiplier == 3
    assert config.fallback_to_language is True
    assert config.shuffle is True
    assert config.enabled is True


def test_env_override_for_seed_count(monkeypatch):
    monkeypatch.setenv("SEED_CONTEXT_N_SEEDS", "2")
    load_seed_context_config.cache_clear()

    try:
        assert load_seed_context_config().n_seeds == 2
    finally:
        load_seed_context_config.cache_clear()


def test_seed_context_injector_uses_configured_seed_count():
    injector = SeedContextInjector(config=_seed_config(n_seeds=1))

    context, seed_ids = injector.get_context_block_no_db(["first seed", "second seed"])

    assert seed_ids == []
    assert "first seed" in context
    assert "second seed" not in context


def test_seed_context_injector_uses_configured_excerpt_length():
    injector = SeedContextInjector(config=_seed_config(max_excerpt_chars=10))

    context, _ = injector.get_context_block_no_db(["abcdefghijklmnopqrstuvwxyz"])

    assert "abcdefghij..." in context


def test_seed_context_injector_can_be_disabled():
    injector = SeedContextInjector(config=_seed_config(enabled=False))

    assert injector.get_context_block_no_db(["seed"]) == ("", [])
