"""Unit tests - SampleSelector stratified review sampling."""

from __future__ import annotations

import pytest

from src.review.sample_selector import SampleSelector, SampleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeCandidate:
    """Minimal stand-in for CandidateResponseORM."""
    def __init__(self, id, language, harm_category, severity, response_type, quality_score, status="passed_filter", run_id=None):
        self.id = id
        self.language = language
        self.harm_category = harm_category
        self.severity = severity
        self.response_type = response_type
        self.quality_score = quality_score
        self.status = status
        self.run_id = run_id


def _make_candidates(language="hausa", n=40):
    """Generate a spread of fake candidates for one language."""
    cands = []
    categories = ["H01", "H02", "H03", "H04"]
    severities = ["S1", "S2", "S3", "S4"]
    rtypes = ["safe", "unsafe"]
    for i in range(n):
        cands.append(_FakeCandidate(
            id=f"{language}-{i}",
            language=language,
            harm_category=categories[i % len(categories)],
            severity=severities[i % len(severities)],
            response_type=rtypes[i % 2],
            quality_score=0.60 + (i / n) * 0.35,  # scores from 0.60 to 0.95
        ))
    return cands


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stratified_sample_returns_correct_count():
    candidates = _make_candidates("hausa", n=40)
    sampled = SampleSelector._stratified_sample(candidates, n=10)
    assert len(sampled) == 10


def test_stratified_sample_fewer_than_n():
    candidates = _make_candidates("yoruba", n=5)
    sampled = SampleSelector._stratified_sample(candidates, n=10)
    # Returns all available when pool smaller than quota
    assert len(sampled) == 5


def test_stratified_sample_zero_quota():
    candidates = _make_candidates("hausa", n=20)
    sampled = SampleSelector._stratified_sample(candidates, n=0)
    assert sampled == []


def test_borderline_split(monkeypatch):
    """Borderline candidates (quality near threshold) should be included."""
    low = _FakeCandidate("b1", "hausa", "H01", "S2", "safe", quality_score=0.62)   # borderline (0.60 + 0.15 margin)
    low2 = _FakeCandidate("b2", "hausa", "H02", "S1", "unsafe", quality_score=0.63)
    high = _FakeCandidate("h1", "hausa", "H03", "S3", "safe", quality_score=0.90)
    high2 = _FakeCandidate("h2", "hausa", "H04", "S4", "unsafe", quality_score=0.95)

    candidates = [low, low2, high, high2]
    selector = SampleSelector()

    # Patch DB query to return our fake candidates
    class FakeSession:
        def query(self, *a): return self
        def filter(self, *a): return self
        def all(self): return candidates

    result = SampleResult()
    ids = selector._sample_language(
        session=FakeSession(),
        language="hausa",
        n=4,
        borderline_fraction=0.5,
        borderline_margin=0.15,
        min_quality=0.60,
        run_id=None,
        result=result,
    )
    assert result.borderline_count > 0
    assert result.high_confidence_count > 0


def test_sample_result_coverage_pct():
    result = SampleResult()
    result.total_eligible = 200
    result.sampled = 50
    d = result.to_dict()
    assert d["review_coverage_pct"] == 25.0


def test_sample_result_zero_eligible():
    result = SampleResult()
    result.total_eligible = 0
    result.sampled = 0
    d = result.to_dict()
    assert d["review_coverage_pct"] == 0
