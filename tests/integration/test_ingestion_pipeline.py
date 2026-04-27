"""Integration test — Ingestion pipeline"""

import uuid
import re
from datetime import datetime, timezone

import pytest
from src.ingestion.seed_normalizer import SeedNormalizer
from src.ingestion.seed_store import SeedStore
from src.ingestion.adapters.local_adapter import LocalAdapter


def test_local_adapter_json(tmp_path):
    """LocalAdapter can load a JSON file."""
    import json
    data = [{"text": "Test sentence in Hausa language."}, {"text": "Another sentence."}]
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    adapter = LocalAdapter()
    records = adapter.fetch(str(f), text_column="text")
    assert len(records) == 2
    assert records[0]["text"] == "Test sentence in Hausa language."


def test_local_adapter_jsonl(tmp_path):
    """LocalAdapter can load a JSONL file."""
    import json
    lines = [json.dumps({"text": f"Sentence {i}."}) for i in range(5)]
    f = tmp_path / "test.jsonl"
    f.write_text("\n".join(lines), encoding="utf-8")

    adapter = LocalAdapter()
    records = adapter.fetch(str(f), text_column="text")
    assert len(records) == 5


def test_local_adapter_txt(tmp_path):
    """LocalAdapter can load a plain text file."""
    f = tmp_path / "test.txt"
    f.write_text("This is a legal document about privacy in South Africa.", encoding="utf-8")

    adapter = LocalAdapter()
    records = adapter.fetch(str(f))
    assert len(records) == 1


def test_normalizer_produces_valid_documents():
    """SeedNormalizer validates and cleans text."""
    source_config = {
        "id": "test_source",
        "name": "Test Source",
        "languages": ["hausa"],
        "harm_domains": ["H01"],
        "license": "CC BY 4.0",
    }
    records = [
        {"text": "Aminu ya je kasuwa don siyan abinci.", "metadata": {}},
        {"text": "  ", "metadata": {}},  # should be skipped
        {"text": "x" * 6000, "metadata": {}},  # should be truncated
    ]
    normalizer = SeedNormalizer()
    docs, skipped = normalizer.normalize(source_config, records)
    assert len(docs) == 2  # short whitespace-only is skipped
    assert skipped == 1
    assert all(len(d.text) <= 5000 for d in docs)


def test_seed_store_deduplication(db_session):
    """SeedStore deduplicates by provenance_hash."""
    from src.schemas.seed import SeedDocument

    source_config = {
        "id": "test_dup",
        "name": "Test Dup",
        "languages": ["hausa"],
        "harm_domains": ["H01"],
        "license": "test",
    }
    records = [{"text": "Hausa text for deduplication test.", "metadata": {}}]
    normalizer = SeedNormalizer()
    docs, _ = normalizer.normalize(source_config, records)

    store = SeedStore()
    inserted1, _ = store.save_batch(docs, db_session)
    inserted2, dups = store.save_batch(docs, db_session)  # should be deduped

    assert inserted1 == 1
    assert inserted2 == 0
    assert dups == 1


def test_seed_store_count(db_session):
    """SeedStore count returns correct language breakdown."""
    source_config = {
        "id": "count_test",
        "name": "Count Test",
        "languages": ["yoruba"],
        "harm_domains": ["H01"],
        "license": "test",
    }
    records = [
        {"text": "Yoruba text example one for testing.", "metadata": {}},
        {"text": "Yoruba text example two for testing purposes.", "metadata": {}},
    ]
    normalizer = SeedNormalizer()
    docs, _ = normalizer.normalize(source_config, records)
    store = SeedStore()
    store.save_batch(docs, db_session)

    counts = store.count(db_session)
    assert counts.get("yoruba", 0) >= 2


def test_normalizer_expands_multilanguage_sources_with_hashes():
    """Multi-language seed sources produce one SHA-256 provenance hash per language."""
    source_config = {
        "id": "multi_source",
        "name": "Multi Source",
        "languages": ["hausa", "yoruba", "shona"],
        "harm_domains": ["H01"],
        "license": "test",
    }
    records = [{"text": "Shared source text long enough to become a valid seed document.", "metadata": {}}]

    docs, skipped = SeedNormalizer().normalize(source_config, records)

    assert skipped == 0
    assert {doc.language for doc in docs} == {"hausa", "yoruba", "shona"}
    assert len({doc.provenance_hash for doc in docs}) == 3
    assert all(re.fullmatch(r"[0-9a-f]{64}", doc.provenance_hash) for doc in docs)
