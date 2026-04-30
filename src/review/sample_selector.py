"""
AfriGuard — Review: SampleSelector

Implements stratified sampling of passed-filter candidates for human review.

Rationale
---------
Given that researchers double as reviewers, full manual review of every
generated candidate is not feasible. Instead, a small but representative
sample is selected to:

  1. Estimate overall dataset quality
  2. Detect systematic prompt/filter/taxonomy problems
  3. Calibrate harm and severity labels across languages
  4. Validate language naturalness and cultural authenticity

The rest of the dataset (not sampled) is exported with
``human_reviewed=False`` in its provenance metadata. This is standard
practice for large synthetic datasets.

Sampling strategy
-----------------
For each language, up to *n_per_language* candidates are selected:

  - **Borderline stratum** (``borderline_fraction`` of the quota):
    candidates with quality_score within 0.15 above the filter threshold.
    These are the most ambiguous cases and benefit most from human eyes.

  - **High-confidence stratum** (remaining quota):
    candidates with quality_score well above the threshold.

Within each stratum, sampling is stratified across
harm_category × severity × response_type to ensure coverage.

After selection, each candidate's status is set to ``sampled_for_review``
so the review UI only shows this subset.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import structlog
from sqlalchemy.orm import Session

from src.config.languages import list_language_names
from src.storage.db import CandidateResponseORM

logger = structlog.get_logger(__name__)

# Default sampling parameters
_DEFAULT_N_PER_LANGUAGE = 50
_DEFAULT_BORDERLINE_FRACTION = 0.20   # 20% of quota from near-threshold cases
_DEFAULT_BORDERLINE_MARGIN = 0.15     # quality_score within this above min_quality
_DEFAULT_MIN_QUALITY = 0.60           # should match pipeline.yaml min_quality_score

_ALL_LANGUAGES = list_language_names()


class SampleResult:
    """Summary of one sampling run."""

    def __init__(self):
        self.total_eligible: int = 0
        self.sampled: int = 0
        self.by_language: dict[str, int] = {}
        self.by_category: dict[str, int] = {}
        self.by_severity: dict[str, int] = {}
        self.borderline_count: int = 0
        self.high_confidence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_eligible": self.total_eligible,
            "sampled": self.sampled,
            "review_coverage_pct": round(
                100 * self.sampled / self.total_eligible, 1
            ) if self.total_eligible else 0,
            "by_language": self.by_language,
            "by_category": self.by_category,
            "by_severity": self.by_severity,
            "borderline_count": self.borderline_count,
            "high_confidence_count": self.high_confidence_count,
        }


class SampleSelector:
    """
    Selects a stratified sample of ``passed_filter`` candidates for human review
    and marks them as ``sampled_for_review`` in the database.

    Usage::

        selector = SampleSelector()
        result = selector.select(
            session,
            n_per_language=50,
            languages=["hausa", "yoruba"],
        )
        print(result.to_dict())
    """

    def select(
        self,
        session: Session,
        n_per_language: int = _DEFAULT_N_PER_LANGUAGE,
        languages: list[str] | None = None,
        borderline_fraction: float = _DEFAULT_BORDERLINE_FRACTION,
        borderline_margin: float = _DEFAULT_BORDERLINE_MARGIN,
        min_quality: float = _DEFAULT_MIN_QUALITY,
        run_id: str | None = None,
        seed: int | None = None,
    ) -> SampleResult:
        """
        Select a stratified review sample and mark candidates in the DB.

        Args:
            session:            SQLAlchemy session.
            n_per_language:     Maximum candidates to sample per language.
            languages:          Restrict to these languages (all if None).
            borderline_fraction: Fraction of quota from near-threshold cases.
            borderline_margin:  Quality margin above min_quality for borderline.
            min_quality:        Filter quality threshold (from pipeline config).
            run_id:             Restrict to candidates from this pipeline run.
            seed:               Random seed for reproducibility.

        Returns:
            SampleResult with counts and breakdown.
        """
        if seed is not None:
            random.seed(seed)

        target_languages = languages or _ALL_LANGUAGES
        result = SampleResult()

        for lang in target_languages:
            sampled_ids = self._sample_language(
                session=session,
                language=lang,
                n=n_per_language,
                borderline_fraction=borderline_fraction,
                borderline_margin=borderline_margin,
                min_quality=min_quality,
                run_id=run_id,
                result=result,
            )

            if sampled_ids:
                # Bulk-update status to sampled_for_review
                session.query(CandidateResponseORM).filter(
                    CandidateResponseORM.id.in_(sampled_ids)
                ).update(
                    {"status": "sampled_for_review"},
                    synchronize_session="fetch",
                )
                session.flush()

                result.by_language[lang] = len(sampled_ids)
                result.sampled += len(sampled_ids)
                logger.info(
                    "sample_selector.language_sampled",
                    language=lang,
                    sampled=len(sampled_ids),
                )

        session.commit()

        logger.info(
            "sample_selector.complete",
            total_eligible=result.total_eligible,
            sampled=result.sampled,
            coverage_pct=result.to_dict()["review_coverage_pct"],
        )
        return result

    def _sample_language(
        self,
        session: Session,
        language: str,
        n: int,
        borderline_fraction: float,
        borderline_margin: float,
        min_quality: float,
        run_id: str | None,
        result: SampleResult,
    ) -> list[str]:
        """Return a list of candidate IDs to sample for this language."""

        query = session.query(CandidateResponseORM).filter(
            CandidateResponseORM.language == language,
            CandidateResponseORM.status == "passed_filter",
        )
        if run_id:
            query = query.filter(CandidateResponseORM.run_id == run_id)

        all_candidates = query.all()
        result.total_eligible += len(all_candidates)

        if not all_candidates:
            return []

        n = min(n, len(all_candidates))

        # Split into borderline and high-confidence
        borderline_threshold = min_quality + borderline_margin
        borderline = [
            c for c in all_candidates
            if c.quality_score is not None and c.quality_score < borderline_threshold
        ]
        high_conf = [
            c for c in all_candidates
            if c.quality_score is None or c.quality_score >= borderline_threshold
        ]

        n_borderline = min(int(n * borderline_fraction), len(borderline))
        n_highconf = min(n - n_borderline, len(high_conf))

        sampled_borderline = self._stratified_sample(borderline, n_borderline)
        sampled_highconf = self._stratified_sample(high_conf, n_highconf)

        result.borderline_count += len(sampled_borderline)
        result.high_confidence_count += len(sampled_highconf)

        # Update aggregated breakdowns
        for c in sampled_borderline + sampled_highconf:
            cat = c.harm_category
            sev = c.severity
            result.by_category[cat] = result.by_category.get(cat, 0) + 1
            result.by_severity[sev] = result.by_severity.get(sev, 0) + 1

        return [c.id for c in sampled_borderline + sampled_highconf]

    @staticmethod
    def _stratified_sample(
        candidates: list[CandidateResponseORM],
        n: int,
    ) -> list[CandidateResponseORM]:
        """
        Sample n candidates stratified by (harm_category, severity, response_type).
        Falls back to random sampling if strata are small.
        """
        if n <= 0 or not candidates:
            return []
        if len(candidates) <= n:
            return candidates

        # Group by stratum
        strata: dict[tuple, list[CandidateResponseORM]] = defaultdict(list)
        for c in candidates:
            key = (c.harm_category, c.severity, c.response_type)
            strata[key].append(c)

        n_strata = len(strata)
        base_per_stratum = max(1, n // n_strata)
        selected: list[CandidateResponseORM] = []

        for stratum_candidates in strata.values():
            take = min(base_per_stratum, len(stratum_candidates))
            selected.extend(random.sample(stratum_candidates, take))
            if len(selected) >= n:
                break

        # Top up with random picks if we're short
        if len(selected) < n:
            remaining = [c for c in candidates if c not in selected]
            extra = min(n - len(selected), len(remaining))
            selected.extend(random.sample(remaining, extra))

        return selected[:n]
