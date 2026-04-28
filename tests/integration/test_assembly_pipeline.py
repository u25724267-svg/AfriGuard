"""Integration test — Assembly pipeline (preference, QA, classification)"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from src.assembly.preference_builder import PreferenceBuilder
from src.assembly.qa_builder import QABuilder
from src.assembly.classification_builder import ClassificationBuilder
from src.assembly.dataset_versioner import DatasetVersioner
from src.storage.db import (
    AnnotationORM,
    CandidateResponseORM,
    DatasetItemORM,
    GeneratedPromptORM,
)


def _seed_prompt_and_candidates(session, language="hausa"):
    """Helper: create a prompt with approved + rejected candidates."""
    prompt_id = str(uuid.uuid4())
    prompt = GeneratedPromptORM(
        id=prompt_id,
        language=language,
        language_code="ha",
        harm_category="H02",
        harm_category_name="Gender-Based Violence",
        severity="S2",
        prompt_text="Test prompt for assembly integration.",
        system_prompt_used="system",
        prompt_template_id="H02_v1",
        prompt_template_version="1.0.0",
        prompt_template_hash="hash123",
        model_used="gpt-4o",
        status="generated",
        created_at=datetime.now(tz=timezone.utc),
        run_id="test-run",
    )
    session.add(prompt)

    safe_cand = CandidateResponseORM(
        id=str(uuid.uuid4()), prompt_id=prompt_id, language=language, language_code="ha",
        harm_category="H02", severity="S2", candidate_index=0,
        response_text="Safe and helpful response about domestic support services.",
        response_type="safe", model_used="gpt-4o", status="passed_filter",
        created_at=datetime.now(tz=timezone.utc), run_id="test-run",
    )
    unsafe_cand = CandidateResponseORM(
        id=str(uuid.uuid4()), prompt_id=prompt_id, language=language, language_code="ha",
        harm_category="H02", severity="S2", candidate_index=1,
        response_text="Harmful response that normalizes violence.",
        response_type="unsafe", model_used="gpt-4o", status="passed_filter",
        created_at=datetime.now(tz=timezone.utc), run_id="test-run",
    )
    session.add(safe_cand)
    session.add(unsafe_cand)

    safe_ann = AnnotationORM(
        id=str(uuid.uuid4()), candidate_id=safe_cand.id, prompt_id=prompt_id,
        annotator_id="test_reviewer", language=language, decision="approve",
        preference_rank=1, created_at=datetime.now(tz=timezone.utc),
    )
    unsafe_ann = AnnotationORM(
        id=str(uuid.uuid4()), candidate_id=unsafe_cand.id, prompt_id=prompt_id,
        annotator_id="test_reviewer", language=language, decision="reject",
        created_at=datetime.now(tz=timezone.utc),
    )
    session.add(safe_ann)
    session.add(unsafe_ann)
    session.commit()

    return prompt_id, safe_cand.id, unsafe_cand.id


def test_preference_and_qa_assembly(db_session):
    _seed_prompt_and_candidates(db_session)

    pref_count = PreferenceBuilder().build(db_session, "0.1.0", "test-run")
    qa_count = QABuilder().build(db_session, "0.1.0", "test-run")
    cls_count = ClassificationBuilder().build(db_session, "0.1.0", "test-run")

    assert pref_count >= 1
    assert qa_count >= 1
    assert cls_count >= 1

    items = db_session.query(DatasetItemORM).all()
    assert len(items) >= 3


def test_assembly_is_idempotent_for_same_version(db_session):
    _seed_prompt_and_candidates(db_session)

    first_pref = PreferenceBuilder().build(db_session, "0.1.0", "first-run")
    first_qa = QABuilder().build(db_session, "0.1.0", "first-run")
    first_cls = ClassificationBuilder().build(db_session, "0.1.0", "first-run")
    first_count = db_session.query(DatasetItemORM).count()

    second_pref = PreferenceBuilder().build(db_session, "0.1.0", "second-run")
    second_qa = QABuilder().build(db_session, "0.1.0", "second-run")
    second_cls = ClassificationBuilder().build(db_session, "0.1.0", "second-run")
    second_count = db_session.query(DatasetItemORM).count()

    assert first_pref >= 1
    assert first_qa >= 1
    assert first_cls >= 1
    assert second_pref == 0
    assert second_qa == 0
    assert second_cls == 0
    assert second_count == first_count


def test_dataset_export(db_session, tmp_path):
    """Test that export writes JSONL files."""
    import os
    os.environ["DATA_DIR"] = str(tmp_path)

    _seed_prompt_and_candidates(db_session)
    PreferenceBuilder().build(db_session, "0.1.0", "test-run")
    QABuilder().build(db_session, "0.1.0", "test-run")

    versioner = DatasetVersioner()
    release_dir = versioner.export(db_session, "0.1.0")

    assert release_dir.exists()
    assert (release_dir / "hausa").exists()
    assert (release_dir / "hausa" / "pku_style" / "prompts.jsonl").exists()
    assert (release_dir / "hausa" / "pku_style" / "qa_pairs.jsonl").exists()
    assert (release_dir / "hausa" / "pku_style" / "preference_pairs.jsonl").exists()
    assert (release_dir / "all_languages" / "pku_style" / "prompts.jsonl").exists()
    assert (release_dir / "all_languages" / "pku_style" / "qa_pairs.jsonl").exists()
    assert (release_dir / "all_languages" / "pku_style" / "preference_pairs.jsonl").exists()
    # At least one JSONL file should exist
    jsonl_files = list(release_dir.rglob("*.jsonl"))
    assert len(jsonl_files) > 0

    qa_records = [
        json.loads(line)
        for line in (release_dir / "hausa" / "pku_style" / "qa_pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    pref_records = [
        json.loads(line)
        for line in (release_dir / "hausa" / "pku_style" / "preference_pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert qa_records[0]["prompt"]
    assert "is_safe" in qa_records[0]
    assert pref_records[0]["better_response_id"] == 0
    assert pref_records[0]["safer_response_id"] == 0

    # Check dataset card
    card = json.loads((release_dir / "dataset_card.json").read_text())
    assert card["version"] == "0.1.0"
    assert card["total_items"] >= 1
    assert "pku_style_outputs" in card


def test_export_deduplicates_existing_duplicate_dataset_rows(db_session, tmp_path):
    """Export should stay clean even if old duplicate assembled rows exist."""
    import os
    os.environ["DATA_DIR"] = str(tmp_path)

    _seed_prompt_and_candidates(db_session)
    PreferenceBuilder().build(db_session, "0.1.0", "test-run")
    QABuilder().build(db_session, "0.1.0", "test-run")

    original = db_session.query(DatasetItemORM).filter_by(item_type="qa_safe").first()
    duplicate = DatasetItemORM(
        id=str(uuid.uuid4()),
        item_type=original.item_type,
        language=original.language,
        language_code=original.language_code,
        harm_category=original.harm_category,
        harm_category_name=original.harm_category_name,
        severity=original.severity,
        prompt_id=original.prompt_id,
        prompt_text=original.prompt_text,
        response_id=original.response_id,
        response_text=original.response_text,
        seed_document_ids=original.seed_document_ids,
        prompt_template_id=original.prompt_template_id,
        annotator_ids=original.annotator_ids,
        models_used=original.models_used,
        dataset_version=original.dataset_version,
        run_id="duplicate-run",
        created_at=datetime.now(tz=timezone.utc),
    )
    db_session.add(duplicate)
    db_session.commit()

    release_dir = DatasetVersioner().export(db_session, "0.1.0")
    qa_records = [
        json.loads(line)
        for line in (release_dir / "hausa" / "pku_style" / "qa_pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    keys = [(record["prompt_id"], record["response_id"], record["is_safe"]) for record in qa_records]
    assert len(keys) == len(set(keys))
