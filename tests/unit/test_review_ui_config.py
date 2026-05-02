"""Unit tests for reviewer UI configuration."""

from src.config.review_ui import load_review_ui_config


def test_review_ui_config_loads_defaults():
    config = load_review_ui_config()

    assert config.tasks_per_page == 10
    assert config.text.app_name == "AfriGuard"
    assert "language naturalness" in config.text.review_instructions


def test_env_override_for_review_task_page_size(monkeypatch):
    monkeypatch.setenv("REVIEW_UI_TASKS_PER_PAGE", "3")
    load_review_ui_config.cache_clear()

    try:
        assert load_review_ui_config().tasks_per_page == 3
    finally:
        load_review_ui_config.cache_clear()
