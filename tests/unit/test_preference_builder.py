"""Unit tests — PreferenceBuilder"""

import uuid
from datetime import datetime, timezone

import pytest
from src.assembly.preference_builder import PreferenceBuilder
from src.storage.db import (
    AnnotationORM,
    CandidateResponseORM,
    DatasetItemORM,
    GeneratedPromptORM,
)


def _make_prompt(session, language="hausa"):
    prompt = GeneratedPromptORM(
        id=str(uuid.uuid4()),
        language=language,
        language_code="ha",
        harm_category="H01",
        harm_category_name="Hate Speech",
        severity="S2",
        prompt_text="Test prompt in Hausa",
        system_prompt_used="Test system prompt",
        prompt_template_id="H01_v1",
        prompt_template_version="1.0.0",
        prompt_template_hash="abc123",
        model_used="gpt-4o",
        status="generated",
        created_at=datetime.now(tz=timezone.utc),
        run_id="test-run",
    )
    session.add(prompt)
    session.flush()
    return prompt


def _make_candidate(session, prompt_id, response_type="safe", status="passed_filter", index=0):
    cand = CandidateResponseORM(
        id=str(uuid.uuid4()),
        prompt_id=prompt_id,
        language="hausa",
        language_code="ha",
        harm_category="H01",
        severity="S2",
        candidate_index=index,
        response_text=f"Response {index}: some text about safety.",
        response_type=response_type,
        model_used="gpt-4o",
        status=status,
        created_at=datetime.now(tz=timezone.utc),
        run_id="test-run",
    )
    session.add(cand)
    session.flush()
    return cand


def _make_annotation(session, candidate_id, prompt_id, decision="approve", rank=None):
    ann = AnnotationORM(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        prompt_id=prompt_id,
        annotator_id="test_annotator",
        language="hausa",
        decision=decision,
        preference_rank=rank,
        created_at=datetime.now(tz=timezone.utc),
    )
    session.add(ann)
    session.flush()
    return ann


def test_preference_pair_created(db_session):
    prompt = _make_prompt(db_session)
    cand_safe = _make_candidate(db_session, prompt.id, "safe", index=0)
    cand_unsafe = _make_candidate(db_session, prompt.id, "unsafe", index=1)

    _make_annotation(db_session, cand_safe.id, prompt.id, decision="approve", rank=1)
    _make_annotation(db_session, cand_unsafe.id, prompt.id, decision="reject")

    builder = PreferenceBuilder()
    count = builder.build(db_session, "0.1.0", "test-run")

    assert count >= 1
    items = db_session.query(DatasetItemORM).filter_by(item_type="preference_pair").all()
    assert len(items) >= 1
    assert items[0].chosen_response_text is not None
    assert items[0].rejected_response_text is not None


def test_no_pair_when_no_annotations(db_session):
    prompt = _make_prompt(db_session)
    _make_candidate(db_session, prompt.id, "safe", index=0)

    builder = PreferenceBuilder()
    count = builder.build(db_session, "0.1.0", "test-run")
    assert count == 0


def test_no_pair_when_only_approved(db_session):
    prompt = _make_prompt(db_session)
    cand = _make_candidate(db_session, prompt.id, "safe", index=0)
    _make_annotation(db_session, cand.id, prompt.id, decision="approve")

    builder = PreferenceBuilder()
    count = builder.build(db_session, "0.1.0", "test-run")
    assert count == 0  # Need both approved and rejected
