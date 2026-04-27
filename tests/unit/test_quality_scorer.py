"""Unit tests — QualityScorer"""

import pytest
from src.filtering.quality_scorer import QualityScorer


@pytest.fixture
def scorer():
    return QualityScorer()


def test_empty_text_scores_zero(scorer):
    assert scorer.score("") == 0.0
    assert scorer.score("   ") == 0.0


def test_very_short_text_scores_low(scorer):
    score = scorer.score("Ok.", "safe")
    # short text gets length_score=0.0, content/coherence drag it below good-text range
    assert score < 0.7  # must score lower than a proper sentence


def test_good_text_scores_high(scorer):
    text = (
        "Ina so in taimaka muku wajen warware matsalar ku. "
        "Don Allah ku tuntube hukumomin kiwon lafiya na gida don samun ingantaccen shawara. "
        "Wannan muhimmin abu ne wanda bai kamata a yi watsi da shi ba."
    )
    score = scorer.score(text, "safe", "hausa")
    assert score >= 0.6


def test_unsafe_refusal_scores_low(scorer):
    text = "I cannot and will not assist with that request. As an AI, I must decline."
    score = scorer.score(text, "unsafe")
    assert score < 0.70  # content=0.1 with weight 0.35 penalises clearly


def test_safe_refusal_scores_normal(scorer):
    text = "I cannot and will not assist with that request. As an AI, I must decline."
    score = scorer.score(text, "safe")
    # For safe responses, refusals are correct — should not be penalized
    assert score >= 0.3


def test_repetitive_text_scores_low(scorer):
    text = "bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad bad"
    score = scorer.score(text, "safe")
    assert score < 0.75  # repetition_score=0.063 with weight 0.30 drags composite


def test_score_batch(scorer):
    batch = [("Hello world this is a test sentence.", "safe"), ("", "safe")]
    scores = scorer.score_batch(batch)
    assert len(scores) == 2
    assert scores[1] == 0.0
