"""Unit tests — HarmRegistry"""

import pytest
from src.taxonomy.harm_registry import HarmRegistry


def test_registry_loads():
    registry = HarmRegistry()
    assert len(registry.list_categories()) == 11


def test_get_category():
    registry = HarmRegistry()
    cat = registry.get_category("H01")
    assert cat.id == "H01"
    assert "Hate" in cat.name
    assert len(cat.subcategories) > 0


def test_get_severity():
    registry = HarmRegistry()
    sev = registry.get_severity("S4")
    assert sev.auto_escalate is True
    assert sev.review_required is True


def test_s1_does_not_require_review():
    registry = HarmRegistry()
    sev = registry.get_severity("S1")
    assert sev.review_required is False
    assert sev.auto_escalate is False


def test_get_legal_references_hausa():
    registry = HarmRegistry()
    refs = registry.get_legal_references("H02", "hausa")
    assert any("Nigeria" in r for r in refs)


def test_get_legal_references_sepedi():
    registry = HarmRegistry()
    refs = registry.get_legal_references("H03", "sepedi")
    assert any("South Africa" in r for r in refs)


def test_get_legal_references_shona():
    registry = HarmRegistry()
    refs = registry.get_legal_references("H03", "shona")
    assert any("Zimbabwe" in r for r in refs)


def test_get_cultural_notes_chichewa():
    registry = HarmRegistry()
    notes = registry.get_cultural_notes("H01", "chichewa")
    assert len(notes) > 0


def test_invalid_category_raises():
    registry = HarmRegistry()
    with pytest.raises(KeyError):
        registry.get_category("H99")


def test_invalid_severity_raises():
    registry = HarmRegistry()
    with pytest.raises(KeyError):
        registry.get_severity("S9")


def test_version_present():
    registry = HarmRegistry()
    assert registry.version != "unknown"
