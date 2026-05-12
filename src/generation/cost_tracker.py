"""
AfriGuard — Generation: CostTracker

Records per-job API costs to the database and enforces budget limits.
Raises only when the hard budget limit is reached.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.config.env import load_project_env
from src.storage.db import GenerationCostORM

load_project_env()
logger = structlog.get_logger(__name__)

_HARD_LIMIT = float(os.environ.get("PIPELINE_BUDGET_HARD_LIMIT_USD", "1500.0"))


class BudgetExceededError(Exception):
    """Raised when the hard budget limit is reached."""


class CostTracker:
    """Records API costs and enforces budget limits."""

    def record(
        self,
        session: Session,
        run_id: str,
        model_id: str,
        job_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        language: str | None = None,
        harm_category: str | None = None,
    ) -> None:
        """Persist a cost record for one LLM API call."""
        orm = GenerationCostORM(
            id=str(uuid.uuid4()),
            run_id=run_id,
            language=language,
            harm_category=harm_category,
            model_id=model_id,
            job_type=job_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            created_at=datetime.now(tz=timezone.utc),
        )
        session.add(orm)

        logger.info(
            "cost_tracker.recorded",
            model=model_id,
            job_type=job_type,
            cost_usd=round(cost_usd, 4),
        )

    def check_budget(self, session: Session) -> None:
        """Check current total cost and raise if hard limit exceeded."""
        total = self._total_cost(session)
        if total >= _HARD_LIMIT:
            raise BudgetExceededError(
                f"Hard budget limit of ${_HARD_LIMIT:.2f} exceeded. "
                f"Current total: ${total:.2f}. Stop pipeline and review."
            )

    def _total_cost(self, session: Session) -> float:
        result = session.query(func.sum(GenerationCostORM.cost_usd)).scalar()
        return float(result or 0.0)

    def summary(self, session: Session) -> dict:
        """Return a cost summary grouped by language and model."""
        from sqlalchemy import func

        rows = (
            session.query(
                GenerationCostORM.language,
                GenerationCostORM.model_id,
                func.sum(GenerationCostORM.prompt_tokens).label("prompt_tokens"),
                func.sum(GenerationCostORM.completion_tokens).label("completion_tokens"),
                func.sum(GenerationCostORM.cost_usd).label("total_usd"),
                func.count(GenerationCostORM.id).label("calls"),
            )
            .group_by(GenerationCostORM.language, GenerationCostORM.model_id)
            .all()
        )

        total = self._total_cost(session)
        return {
            "total_usd": round(total, 4),
            "by_language_model": [
                {
                    "language": r.language,
                    "model_id": r.model_id,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_usd": round(float(r.total_usd or 0), 4),
                    "api_calls": r.calls,
                }
                for r in rows
            ],
        }
