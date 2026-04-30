"""Integration test — Ingestion pipeline"""

import uuid
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from src.ingestion.seed_normalizer import SeedNormalizer
from src.ingestion.seed_store import SeedStore
from src.ingestion.adapters.local_adapter import LocalAdapter
from src.ingestion.seed_fetcher import SeedFetcher


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


def test_seed_fetcher_uses_language_specific_hf_config(tmp_path, monkeypatch):
    """Language-filtered fetches pass the matching HF config and narrow source languages."""
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        """
sources:
  - id: "multi_news"
    type: "huggingface"
    hf_path: "example/news"
    hf_config_by_language:
      shona: "sna"
      hausa: "hau"
    languages: ["shona", "hausa"]
    harm_domains: ["H04"]
    text_column: "text"
  - id: "disabled_source"
    enabled: false
    type: "huggingface"
    hf_path: "example/disabled"
    languages: ["shona"]
""",
        encoding="utf-8",
    )

    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return [{"text": "Shona news text long enough to become a seed.", "metadata": {}}]

    fetcher = SeedFetcher(sources_path=sources)
    monkeypatch.setattr(fetcher._hf_adapter, "fetch", fake_fetch)

    batches = fetcher.fetch_all(max_samples_per_source=10, languages=["shona"])

    assert len(batches) == 1
    source_config, records = batches[0]
    assert source_config["languages"] == ["shona"]
    assert records
    assert calls[0]["hf_config"] == "sna"


def test_configured_seed_source_ids_are_unique():
    """The production seed registry should not contain duplicate source IDs."""
    repo_root = Path(__file__).resolve().parents[2]
    sources_path = repo_root / "configs" / "seed_sources.yaml"
    config = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    source_ids = [source["id"] for source in config["sources"]]

    assert len(source_ids) == len(set(source_ids))


def test_vukuzenzele_sepedi_source_is_configured():
    """Sepedi should have a high-volume government/context seed source."""
    repo_root = Path(__file__).resolve().parents[2]
    sources_path = repo_root / "configs" / "seed_sources.yaml"
    config = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in config["sources"]}

    vukuzenzele = sources["vukuzenzele_sepedi"]
    assert vukuzenzele["type"] == "huggingface"
    assert vukuzenzele["hf_path"] == "dsfsi/vukuzenzele-monolingual"
    assert vukuzenzele["hf_config"] == "nso"
    assert vukuzenzele["text_column"] == "text"
    assert "sepedi" in vukuzenzele["languages"]
    assert {"H02", "H03", "H04", "context"}.issubset(set(vukuzenzele["harm_domains"]))


def test_configured_legal_seed_files_exist_and_load():
    """Legal seed sources referenced in config should exist and provide context."""
    repo_root = Path(__file__).resolve().parents[2]
    sources_path = repo_root / "configs" / "seed_sources.yaml"
    config = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    legal_sources = [
        source for source in config["sources"]
        if str(source.get("local_path", "")).startswith("data/seeds/legal/")
    ]

    assert legal_sources, "Expected at least one configured legal seed source"

    adapter = LocalAdapter()
    for source in legal_sources:
        path = repo_root / source["local_path"]
        assert path.exists(), f"Missing configured legal seed file: {path}"
        records = adapter.fetch(path, text_column=source.get("text_column", "text"))
        assert records, f"Configured legal seed file loaded no records: {path}"
