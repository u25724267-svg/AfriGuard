"""Unit tests - autoresume checkpoint tracker."""

from src.pipeline.resume import PipelineResumeTracker
from src.storage.db import PipelineRunORM, PipelineStageRunORM


def test_start_or_resume_run_creates_checkpoint(db_session):
    tracker = PipelineResumeTracker(db_session)

    run = tracker.start_or_resume_run(
        run_id="run-1",
        resume=False,
        language="hausa",
        version="0.1.0",
        n_prompts=3,
    )

    assert run.id == "run-1"
    assert run.status == "running"
    assert run.requested_language == "hausa"
    assert db_session.get(PipelineRunORM, "run-1") is not None


def test_stage_completion_is_resumable(db_session):
    tracker = PipelineResumeTracker(db_session)
    tracker.start_or_resume_run(
        run_id="run-2",
        resume=False,
        language=None,
        version="0.1.0",
        n_prompts=5,
    )

    tracker.mark_stage_started("run-2", "generate")
    tracker.mark_stage_completed("run-2", "generate")

    assert tracker.stage_is_completed("run-2", "generate") is True
    stage = (
        db_session.query(PipelineStageRunORM)
        .filter(
            PipelineStageRunORM.run_id == "run-2",
            PipelineStageRunORM.stage_name == "generate",
        )
        .one()
    )
    assert stage.status == "completed"
    assert stage.attempts == 1


def test_resume_latest_failed_run(db_session):
    tracker = PipelineResumeTracker(db_session)
    tracker.start_or_resume_run(
        run_id="run-3",
        resume=False,
        language="yoruba",
        version="0.1.0",
        n_prompts=2,
    )
    tracker.mark_stage_started("run-3", "filter")
    tracker.mark_stage_failed("run-3", "filter", "boom")

    resumed = tracker.start_or_resume_run(
        run_id=None,
        resume=True,
        language="yoruba",
        version="0.1.0",
        n_prompts=2,
    )

    assert resumed.id == "run-3"
    assert resumed.status == "running"
    assert resumed.error is None
