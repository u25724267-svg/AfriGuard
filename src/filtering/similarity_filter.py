"""
AfriGuard — Filtering: SimilarityFilter

Removes near-duplicate candidate responses within the same prompt batch
using multilingual sentence embeddings and cosine similarity.

Model: paraphrase-multilingual-mpnet-base-v2 (supports 50+ languages
including Hausa and Yoruba; acceptable for Sepedi, Chichewa as proxy).

For Yao — which is not in the model's training set — similarity is computed
on character-level n-grams as a fallback.
"""

from __future__ import annotations

import structlog
import numpy as np

from src.config.languages import get_char_ngram_similarity_languages

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"
_DEFAULT_THRESHOLD = 0.85

# Languages not well-supported by the embedding model — use character n-gram fallback
_CHAR_NGRAM_FALLBACK = get_char_ngram_similarity_languages()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _char_ngram_similarity(text1: str, text2: str, n: int = 3) -> float:
    """Character n-gram Jaccard similarity as a fallback for unsupported languages."""
    def ngrams(text: str) -> set:
        text = text.lower()
        return {text[i:i+n] for i in range(len(text) - n + 1)}

    ng1, ng2 = ngrams(text1), ngrams(text2)
    if not ng1 or not ng2:
        return 0.0
    return len(ng1 & ng2) / len(ng1 | ng2)


class SimilarityFilter:
    """
    Filters near-duplicate candidates within a prompt batch.

    Usage:
        sf = SimilarityFilter(threshold=0.85)
        keep_indices = sf.filter(texts, language="hausa")
    """

    def __init__(
        self,
        threshold: float = _DEFAULT_THRESHOLD,
        model_name: str = _DEFAULT_MODEL,
    ):
        self.threshold = threshold
        self.model_name = model_name
        self._model = None  # Lazy load

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("similarity_filter.loading_model", model=self.model_name)
                self._model = SentenceTransformer(self.model_name)
            except ImportError:
                raise ImportError(
                    "Install sentence-transformers: pip install sentence-transformers"
                )
        return self._model

    def filter(
        self,
        texts: list[str],
        language: str = "unknown",
    ) -> tuple[list[int], list[float]]:
        """
        Identify which candidates to keep (non-near-duplicates).

        Args:
            texts:    List of candidate response texts
            language: Language name (determines embedding vs. char-ngram method)

        Returns:
            (keep_indices, max_similarity_scores)
            keep_indices: indices of texts to keep
            max_similarity_scores: for each text, its max similarity to any previously kept text
        """
        if len(texts) <= 1:
            return list(range(len(texts))), [0.0] * len(texts)

        use_char_ngram = language.lower() in _CHAR_NGRAM_FALLBACK

        if use_char_ngram:
            return self._filter_char_ngram(texts)
        else:
            return self._filter_embeddings(texts)

    def _filter_embeddings(
        self, texts: list[str]
    ) -> tuple[list[int], list[float]]:
        model = self._get_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        keep: list[int] = []
        max_sims: list[float] = [0.0] * len(texts)

        for i, emb in enumerate(embeddings):
            max_sim = 0.0
            for j in keep:
                sim = _cosine_similarity(emb, embeddings[j])
                max_sim = max(max_sim, sim)

            max_sims[i] = max_sim

            if max_sim < self.threshold:
                keep.append(i)
            else:
                logger.debug(
                    "similarity_filter.near_duplicate_found",
                    index=i,
                    max_similarity=round(max_sim, 4),
                    threshold=self.threshold,
                )

        logger.info(
            "similarity_filter.filtered",
            total=len(texts),
            kept=len(keep),
            removed=len(texts) - len(keep),
        )
        return keep, max_sims

    def _filter_char_ngram(
        self, texts: list[str]
    ) -> tuple[list[int], list[float]]:
        keep: list[int] = []
        max_sims: list[float] = [0.0] * len(texts)

        for i, text in enumerate(texts):
            max_sim = 0.0
            for j in keep:
                sim = _char_ngram_similarity(text, texts[j])
                max_sim = max(max_sim, sim)

            max_sims[i] = max_sim

            if max_sim < self.threshold:
                keep.append(i)

        logger.info(
            "similarity_filter.char_ngram_filtered",
            total=len(texts),
            kept=len(keep),
        )
        return keep, max_sims

    def score_pair(self, text1: str, text2: str, language: str = "unknown") -> float:
        """Compute similarity between two texts."""
        if language.lower() in _CHAR_NGRAM_FALLBACK:
            return _char_ngram_similarity(text1, text2)
        model = self._get_model()
        embs = model.encode([text1, text2], convert_to_numpy=True)
        return _cosine_similarity(embs[0], embs[1])
