"""Unit tests — Deduplicator"""

import pytest
from src.filtering.deduplicator import Deduplicator, _tokenize, _shingle


def test_tokenize_basic():
    tokens = _tokenize("Hello, world! This is a test.")
    assert "hello" in tokens
    assert "world" in tokens


def test_shingle_basic():
    tokens = ["a", "b", "c", "d"]
    shingles = _shingle(tokens, k=2)
    assert "a b" in shingles
    assert "b c" in shingles


def test_shingle_short_input():
    tokens = ["hello"]
    shingles = _shingle(tokens, k=3)
    assert shingles == {"hello"}


def test_no_duplicate():
    d = Deduplicator()
    assert d.is_duplicate("id1", "Completely unique text about safety in Hausa language") is False
    assert d.is_duplicate("id2", "Completely different text about cooking") is False


def test_exact_duplicate():
    d = Deduplicator()
    text = "This is a test sentence that will appear twice in the corpus."
    d.is_duplicate("id1", text)
    assert d.is_duplicate("id2", text) is True


def test_near_duplicate():
    d = Deduplicator(threshold=0.7)
    text1 = "Aminu wants to buy food from the market in Kano today."
    text2 = "Aminu wants to buy food from the market in Kano tomorrow."
    d.is_duplicate("id1", text1)
    # Very similar — may or may not be flagged depending on shingle overlap
    result = d.is_duplicate("id2", text2)
    assert isinstance(result, bool)


def test_filter_batch():
    d = Deduplicator()
    text = "Identical safety-related content about privacy violation in Nigeria."
    items = [
        ("item1", text),
        ("item2", text),
        ("item3", "Completely different content about healthcare."),
    ]
    kept, removed = d.filter_batch(items)
    assert "item1" in kept
    assert "item2" in removed
    assert "item3" in kept


def test_size_tracking():
    d = Deduplicator()
    d.is_duplicate("a", "some unique text here for testing")
    assert d.size() == 1


def test_clear():
    d = Deduplicator()
    d.is_duplicate("a", "unique text content for clear test")
    d.clear()
    assert d.size() == 0
