"""Integration test — Assembly pipeline (preference, QA, classification)"""

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
    # At least one JSONL file should exist
    jsonl_files = list(release_dir.rglob("*.jsonl"))
    assert len(jsonl_files) > 0

    # Check dataset card
    import json
    card = json.loads((release_dir / "dataset_card.json").read_text())
    assert card["version"] == "0.1.0"
    assert card["total_items"] >= 1
