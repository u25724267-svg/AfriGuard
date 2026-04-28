"""Unit tests - review queue candidate counts."""

from datetime import datetime, timezone

from src.review.task_assigner import TaskAssigner
from src.storage.db import CandidateResponseORM, GeneratedPromptORM


def _make_prompt(db_session):
    prompt = GeneratedPromptORM(
        id="prompt-review-counts",
        language="shona",
        language_code="sn",
        harm_category="H03",
        harm_category_name="Privacy Violations",
        severity="S2",
        prompt_text="Prompt text",
        system_prompt_used="System prompt",
        prompt_template_id="template-review-counts",
        prompt_template_version="1.0.0",
        prompt_template_hash="hash",
        seed_document_ids=[],
        legal_context_used="Cyber and Data Protection Act",
        entities_injected=[],
        model_used="gpt-4o-mini",
        generation_params={},
        created_at=datetime.now(tz=timezone.utc),
        run_id="run-review-counts",
        status="generated",
    )
    db_session.add(prompt)
    return prompt


def _make_candidate(db_session, candidate_id, status="sampled_for_review", index=0):
    candidate = CandidateResponseORM(
        id=candidate_id,
        prompt_id="prompt-review-counts",
        language="shona",
        language_code="sn",
        harm_category="H03",
        severity="S2",
        candidate_index=index,
        response_text=f"Candidate response {index}",
        response_type="safe",
        model_used="gpt-4o-mini",
        generation_params={},
        status=status,
        created_at=datetime.now(tz=timezone.utc),
        run_id="run-review-counts",
    )
    db_session.add(candidate)
    return candidate


def test_pending_count_tracks_candidate_items_not_prompt_groups(db_session):
    _make_prompt(db_session)
    first = _make_candidate(db_session, "candidate-one", index=0)
    _make_candidate(db_session, "candidate-two", index=1)
    db_session.commit()

    assigner = TaskAssigner()

    assert assigner.count_pending_items(db_session, "reviewer_shona") == 2
    assert len(assigner.get_pending_tasks(db_session, "reviewer_shona")) == 1

    first.status = "approved"
    db_session.commit()

    tasks = assigner.get_pending_tasks(db_session, "reviewer_shona")
    assert assigner.count_pending_items(db_session, "reviewer_shona") == 1
    assert len(tasks) == 1
    assert len(tasks[0].candidates) == 1


def test_prompt_group_disappears_after_all_candidates_reviewed(db_session):
    _make_prompt(db_session)
    _make_candidate(db_session, "candidate-one", status="approved", index=0)
    _make_candidate(db_session, "candidate-two", status="rejected", index=1)
    db_session.commit()

    assigner = TaskAssigner()

    assert assigner.count_pending_items(db_session, "reviewer_shona") == 0
    assert assigner.get_pending_tasks(db_session, "reviewer_shona") == []
