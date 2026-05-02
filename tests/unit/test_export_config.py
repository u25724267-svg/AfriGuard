"""Unit tests for dataset export policy configuration."""

from src.config.export import load_export_config


def test_export_config_loads_defaults():
    config = load_export_config()

    assert config.write_native_jsonl is True
    assert config.write_pku_style_jsonl is True
    assert config.write_all_languages is True
    assert config.write_dataset_card is True
    assert "qa_safe" in config.native_item_types


def test_env_override_can_disable_pku_style_exports(monkeypatch):
    monkeypatch.setenv("EXPORT_WRITE_PKU_STYLE_JSONL", "false")
    load_export_config.cache_clear()

    try:
        assert load_export_config().write_pku_style_jsonl is False
    finally:
        load_export_config.cache_clear()
