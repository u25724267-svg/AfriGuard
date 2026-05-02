"""Unit tests for review sampling policy configuration."""

from types import SimpleNamespace

from src.config.review_sampling import ReviewSamplingConfig, load_review_sampling_config
import src.review.sample_selector as sample_selector_mod
from src.review.sample_selector import SampleSelector

from tests.unit.test_sample_selector import _make_candidates


def test_review_sampling_config_loads_defaults():
    config = load_review_sampling_config()

    assert config.n_per_language == 50
    assert config.borderline_fraction == 0.20
    assert config.borderline_margin == 0.15


def test_env_override_for_review_sampling_quota(monkeypatch):
    monkeypatch.setenv("REVIEW_SAMPLE_N_PER_LANGUAGE", "7")
    load_review_sampling_config.cache_clear()

    try:
        assert load_review_sampling_config().n_per_language == 7
    finally:
        load_review_sampling_config.cache_clear()


def test_sample_selector_uses_configured_defaults(monkeypatch):
    candidates = _make_candidates("hausa", n=5)

    class FakeSession:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def all(self):
            return candidates

        def update(self, *args, **kwargs):
            return len(candidates)

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(
        sample_selector_mod,
        "load_review_sampling_config",
        lambda: ReviewSamplingConfig(
            n_per_language=2,
            borderline_fraction=0.0,
            borderline_margin=0.15,
        ),
    )
    monkeypatch.setattr(
        sample_selector_mod,
        "load_filtering_config",
        lambda: SimpleNamespace(min_quality_score=0.60),
    )

    result = SampleSelector().select(FakeSession(), languages=["hausa"], seed=42)

    assert result.sampled == 2
