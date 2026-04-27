"""Unit tests — SimilarityFilter"""

import pytest
from src.filtering.similarity_filter import SimilarityFilter, _char_ngram_similarity


def test_char_ngram_identical():
    sim = _char_ngram_similarity("hello world", "hello world")
    assert sim == 1.0


def test_char_ngram_different():
    sim = _char_ngram_similarity("hello world", "goodbye universe")
    assert sim < 0.3


def test_char_ngram_empty():
    sim = _char_ngram_similarity("", "hello")
    assert sim == 0.0


def test_filter_single_item():
    sf = SimilarityFilter(threshold=0.85)
    keep, sims = sf.filter(["only one response"], language="hausa")
    assert keep == [0]
    assert sims == [0.0]


def test_filter_empty():
    sf = SimilarityFilter(threshold=0.85)
    keep, sims = sf.filter([], language="hausa")
    assert keep == []


def test_filter_yao_uses_char_ngram():
    """Yao should use character n-gram fallback without loading embedding model."""
    sf = SimilarityFilter(threshold=0.85)
    texts = [
        "Alimu anafuna msaada wa kupata kazi mpya.",
        "Alimu anafuna msaada wa kupata kazi mpya.",  # exact duplicate
        "Fatuma anapika chakula cha asubuhi.",
    ]
    keep, sims = sf.filter(texts, language="yao")
    # The duplicate should be removed
    assert 1 not in keep
    assert 2 in keep


def test_score_pair_identical():
    sf = SimilarityFilter()
    # Use char ngram for yao to avoid loading model in unit tests
    sim = sf.score_pair("same text here", "same text here", language="yao")
    assert sim == 1.0


def test_score_pair_very_different():
    sf = SimilarityFilter()
    sim = sf.score_pair(
        "completely different content about food",
        "xyz abc 123 unrelated topic",
        language="yao",
    )
    assert sim < 0.5
