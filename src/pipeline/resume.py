"""
AfriGuard pipeline autoresume helpers.

The CLI remains simple, but each run now has durable stage checkpoints in the
database. A failed `run-all` can resume from the first incomplete stage while
reusing the same run_id for generated prompts/candidates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.storage.db import PipelineRunORM, PipelineStageRunORM


RUN_ALL_STAGES = ("bootstrap_db", "ingest_seeds", "generate", "filter", "assign_review")
TERMINAL_SUCCESS = "completed"


def utcnow() -> datetime:
    """Return a timezone-aware timestamp for checkpoint records."""
    return datetime.now(tz=timezone.utc)


class PipelineResumeTracker:
    """Persistence layer for resumable CLI pipeline runs."""

    def __init__(self, session: Session):
        self.session = session

    def start_or_resume_run(
        self,
        *,
        run_id: str | None,
        resume: bool,
        language: str | None,
        version: str,
        n_prompts: int,
    ) -> PipelineRunORM:
        """Create a new run, resume a named run, or find the latest incomplete run."""
        now = utcnow()

        run: PipelineRunORM | None = None
        if run_id:
            run = self.session.get(PipelineRunORM, run_id)
            if run is None and resume:
                raise ValueError(f"No pipeline run found for --run-id {run_id}")
        elif resume:
            run = (
                self.session.query(PipelineRunORM)
                .filter(PipelineRunORM.status.in_(("running", "failed", "paused")))
                .order_by(PipelineRunORM.updated_at.desc())
                .first()
            )
            if run is None:
                raise ValueError("No incomplete pipeline run found to resume.")

        if run is None:
            run = PipelineRunORM(
                id=run_id or str(uuid.uuid4()),
                status="running",
                requested_language=language,
                dataset_version=version,
                n_prompts=n_prompts,
                metadata_={"resume_enabled": True},
                started_at=now,
                updated_at=now,
            )
            self.session.add(run)
        else:
            run.status = "running"
            run.error = None
            run.requested_language = language
            run.dataset_version = version
            run.n_prompts = n_prompts
            run.updated_at = now

        self.session.commit()
        return run

    def stage_is_completed(self, run_id: str, stage_name: str) -> bool:
        stage = self._get_stage(run_id, stage_name)
        return bool(stage and stage.status == TERMINAL_SUCCESS)

    def mark_stage_started(
        self,
        run_id: str,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> PipelineStageRunORM:
        now = utcnow()
        stage = self._get_or_create_stage(run_id, stage_name)
        stage.status = "running"
        stage.error = None
        stage.started_at = stage.started_at or now
        stage.updated_at = now
        stage.attempts = (stage.attempts or 0) + 1
        if metadata:
            existing = dict(stage.metadata_ or {})
            existing.update(metadata)
            stage.metadata_ = existing

        run = self.session.get(PipelineRunORM, run_id)
        if run:
            run.status = "running"
            run.current_stage = stage_name
            run.updated_at = now

        self.session.commit()
        return stage

    def mark_stage_completed(
        self,
        run_id: str,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utcnow()
        stage = self._get_or_create_stage(run_id, stage_name)
        stage.status = TERMINAL_SUCCESS
        stage.error = None
        stage.completed_at = now
        stage.updated_at = now
        if metadata:
            existing = dict(stage.metadata_ or {})
            existing.update(metadata)
            stage.metadata_ = existing

        run = self.session.get(PipelineRunORM, run_id)
        if run:
            run.current_stage = stage_name
            run.updated_at = now

        self.session.commit()

    def mark_stage_failed(self, run_id: str, stage_name: str, error: str) -> None:
        now = utcnow()
        stage = self._get_or_create_stage(run_id, stage_name)
        stage.status = "failed"
        stage.error = error
        stage.updated_at = now

        run = self.session.get(PipelineRunORM, run_id)
        if run:
            run.status = "failed"
            run.current_stage = stage_name
            run.error = error
            run.updated_at = now

        self.session.commit()

    def mark_run_paused(self, run_id: str, message: str) -> None:
        run = self.session.get(PipelineRunORM, run_id)
        if run:
            run.status = "paused"
            run.error = message
            run.updated_at = utcnow()
            self.session.commit()

    def mark_run_completed(self, run_id: str) -> None:
        now = utcnow()
        run = self.session.get(PipelineRunORM, run_id)
        if run:
            run.status = TERMINAL_SUCCESS
            run.current_stage = None
            run.error = None
            run.completed_at = now
            run.updated_at = now
            self.session.commit()

    def _get_stage(self, run_id: str, stage_name: str) -> PipelineStageRunORM | None:
        return (
            self.session.query(PipelineStageRunORM)
            .filter(
                PipelineStageRunORM.run_id == run_id,
                PipelineStageRunORM.stage_name == stage_name,
            )
            .first()
        )

    def _get_or_create_stage(self, run_id: str, stage_name: str) -> PipelineStageRunORM:
        stage = self._get_stage(run_id, stage_name)
        if stage:
            return stage

        stage = PipelineStageRunORM(
            id=str(uuid.uuid4()),
            run_id=run_id,
            stage_name=stage_name,
            status="pending",
            attempts=0,
        )
        self.session.add(stage)
        self.session.flush()
        return stage
