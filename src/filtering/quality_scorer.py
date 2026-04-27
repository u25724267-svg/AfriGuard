"""
AfriGuard — Filtering: QualityScorer

Scores candidate responses on multiple quality dimensions:
  1. Length score     — within acceptable bounds
  2. Repetition score — penalizes repetitive text
  3. Coherence score  — heuristic: sentence count vs word count ratio
  4. Harm relevance   — (optional) LLM judge scoring relevance to harm category

Final quality_score is a weighted average in [0.0, 1.0].
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

_MIN_CHARS = 30
_MAX_CHARS = 2000
_OPTIMAL_MIN_CHARS = 80
_OPTIMAL_MAX_CHARS = 800


def _length_score(text: str) -> float:
    n = len(text)
    if n < _MIN_CHARS or n > _MAX_CHARS:
        return 0.0
    if _OPTIMAL_MIN_CHARS <= n <= _OPTIMAL_MAX_CHARS:
        return 1.0
    if n < _OPTIMAL_MIN_CHARS:
        return n / _OPTIMAL_MIN_CHARS
    # Linearly decrease for very long responses
    return max(0.3, 1.0 - (n - _OPTIMAL_MAX_CHARS) / (_MAX_CHARS - _OPTIMAL_MAX_CHARS))


def _repetition_score(text: str) -> float:
    """Penalize repetitive n-grams."""
    words = text.lower().split()
    if len(words) < 5:
        return 0.5
    # Count unique bigrams
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    if not bigrams:
        return 1.0
    unique_ratio = len(set(bigrams)) / len(bigrams)
    return min(1.0, unique_ratio * 1.2)


def _coherence_score(text: str) -> float:
    """
    Heuristic coherence: penalize single-sentence very long responses
    and very fragmented text.
    """
    sentences = re.split(r"[.!?؟।]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    word_count = len(text.split())
    sentence_count = max(1, len(sentences))

    # Ideal: 10-30 words per sentence
    avg_words_per_sentence = word_count / sentence_count
    if 8 <= avg_words_per_sentence <= 40:
        return 1.0
    elif avg_words_per_sentence < 3:
        return 0.4
    elif avg_words_per_sentence > 60:
        return 0.6
    return 0.8


def _empty_or_refusal_score(text: str, response_type: str) -> float:
    """
    Penalize empty responses or obvious refusals when an unsafe response was expected.
    For safe responses, refusals are actually correct — don't penalize them.
    """
    if not text.strip():
        return 0.0

    lower = text.lower()
    refusal_signals = [
        "i cannot", "i'm unable", "i can't", "i apologize", "as an ai",
        "i must decline", "i won't", "i will not", "sorry, but",
    ]
    has_refusal = any(sig in lower for sig in refusal_signals)

    if response_type == "unsafe" and has_refusal:
        # Model refused to generate unsafe content — filter this out
        return 0.1
    return 1.0


class QualityScorer:
    """
    Computes a quality score for a candidate response.

    Weights:
      length_score:     0.3
      repetition_score: 0.25
      coherence_score:  0.25
      content_score:    0.20  (refusal check)
    """

    WEIGHTS = {
        "length": 0.15,
        "repetition": 0.30,
        "coherence": 0.20,
        "content": 0.35,
    }

    def score(
        self,
        text: str,
        response_type: str = "safe",
        expected_language: str | None = None,
    ) -> float:
        """
        Compute overall quality score for a response text.

        Args:
            text:              The candidate response text
            response_type:     'safe' or 'unsafe'
            expected_language: Used for future language-aware scoring (not yet implemented)

        Returns:
            Float in [0.0, 1.0]
        """
        if not text or not text.strip():
            return 0.0

        scores = {
            "length": _length_score(text),
            "repetition": _repetition_score(text),
            "coherence": _coherence_score(text),
            "content": _empty_or_refusal_score(text, response_type),
        }

        composite = sum(scores[k] * self.WEIGHTS[k] for k in scores)
        composite = round(min(1.0, max(0.0, composite)), 4)

        logger.debug(
            "quality_scorer.scored",
            composite=composite,
            **{f"score_{k}": round(v, 3) for k, v in scores.items()},
        )
        return composite

    def score_batch(
        self,
        texts_with_types: list[tuple[str, str]],
    ) -> list[float]:
        """Score a batch of (text, response_type) tuples."""
        return [self.score(text, rtype) for text, rtype in texts_with_types]
