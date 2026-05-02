"""Unit tests for filtering policy configuration."""

from src.config.filtering import load_filtering_config
from src.filtering.deduplicator import Deduplicator
from src.filtering.language_detector import LanguageDetector, LanguageDetectionResult


def test_filtering_config_loads_defaults():
    config = load_filtering_config()

    assert config.min_quality_score == 0.60
    assert config.similarity_threshold == 0.85
    assert config.deduplication_threshold == 0.70
    assert config.language_detection.default_threshold == 0.40
    assert config.language_detection.low_resource_threshold == 0.35


def test_env_override_for_quality_threshold(monkeypatch):
    monkeypatch.setenv("PIPELINE_MIN_QUALITY_SCORE", "0.72")
    load_filtering_config.cache_clear()

    try:
        assert load_filtering_config().min_quality_score == 0.72
    finally:
        load_filtering_config.cache_clear()


def test_language_detector_uses_configured_threshold(monkeypatch):
    config = load_filtering_config()
    detector = LanguageDetector(config=config)
    monkeypatch.setattr(
        detector,
        "detect",
        lambda text, expected_language: LanguageDetectionResult("ha", 0.39, "test"),
    )

    ok, _ = detector.is_acceptable("Rubutu mai tsawo don gwaji.", "hausa")

    assert ok is False


def test_deduplicator_uses_configured_default_threshold():
    assert Deduplicator().threshold == load_filtering_config().deduplication_threshold
