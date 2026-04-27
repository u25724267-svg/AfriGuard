"""
AfriGuard — Observability: metrics helpers.

Lightweight metrics using Python counters + structlog.
For production, swap with prometheus_client.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PipelineMetrics:
    """In-process metrics accumulator."""
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    timers: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def increment(self, name: str, value: int = 1, **labels: Any) -> None:
        key = name + "".join(f"_{k}={v}" for k, v in sorted(labels.items()))
        self.counters[key] += value
        logger.debug("metric.increment", name=name, value=value, **labels)

    def record_duration(self, name: str, seconds: float, **labels: Any) -> None:
        key = name + "".join(f"_{k}={v}" for k, v in sorted(labels.items()))
        self.timers[key].append(seconds)

    def summary(self) -> dict[str, Any]:
        timer_summary = {
            k: {
                "count": len(v),
                "mean_s": round(sum(v) / len(v), 4) if v else 0,
                "total_s": round(sum(v), 4),
            }
            for k, v in self.timers.items()
        }
        return {"counters": dict(self.counters), "timers": timer_summary}


# Module-level singleton
_metrics = PipelineMetrics()


def get_metrics() -> PipelineMetrics:
    return _metrics


class timer:
    """Context manager to record execution time."""
    def __init__(self, name: str, **labels: Any):
        self.name = name
        self.labels = labels
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        elapsed = time.perf_counter() - self._start
        _metrics.record_duration(self.name, elapsed, **self.labels)
        logger.debug("metric.timer", name=self.name, seconds=round(elapsed, 4), **self.labels)
