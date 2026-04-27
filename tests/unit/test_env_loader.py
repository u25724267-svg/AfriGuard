"""Unit tests - safe dotenv loading."""

from src.config.env import load_project_env


def test_load_project_env_loads_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AFRIGUARD_TEST_VALUE=loaded\n", encoding="utf-8")
    monkeypatch.delenv("AFRIGUARD_TEST_VALUE", raising=False)

    assert load_project_env(env_file) is True
    assert __import__("os").environ["AFRIGUARD_TEST_VALUE"] == "loaded"


def test_load_project_env_does_not_override_existing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AFRIGUARD_TEST_VALUE=file-value\n", encoding="utf-8")
    monkeypatch.setenv("AFRIGUARD_TEST_VALUE", "shell-value")

    assert load_project_env(env_file) is True
    assert __import__("os").environ["AFRIGUARD_TEST_VALUE"] == "shell-value"


def test_load_project_env_missing_file_returns_false(tmp_path):
    assert load_project_env(tmp_path / ".env") is False
