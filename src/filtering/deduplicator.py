"""
AfriGuard — Filtering: Deduplicator

Cross-batch near-deduplication using MinHash LSH.
Prevents the same prompt or response from appearing in multiple
generation batches or across languages.

Uses datasketch MinHash with word shingles.
"""

from __future__ import annotations

import re
import struct
import structlog

from src.config.filtering import load_filtering_config

logger = structlog.get_logger(__name__)

_NUM_PERM = 128          # MinHash permutations (higher = more accurate)
_SHINGLE_SIZE = 3        # Word n-gram size for shingling
_THRESHOLD = 0.7         # Jaccard similarity threshold for near-duplicates


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())


def _shingle(tokens: list[str], k: int = _SHINGLE_SIZE) -> set[str]:
    """Generate k-gram shingles from a token list."""
    if len(tokens) < k:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


class Deduplicator:
    """
    MinHash-based near-deduplication across the full candidate corpus.

    Maintains an in-memory LSH index. For persistence across runs,
    call save() / load() to serialize to disk.
    """

    def __init__(
        self,
        num_perm: int = _NUM_PERM,
        threshold: float | None = None,
    ):
        self.num_perm = num_perm
        self.threshold = threshold if threshold is not None else load_filtering_config().deduplication_threshold
        self._lsh = None
        self._seen_ids: dict[str, str] = {}  # minhash_key -> original_id
        self._initialized = False

    def _get_lsh(self):
        if not self._initialized:
            try:
                from datasketch import MinHashLSH
                self._lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
                self._initialized = True
            except ImportError:
                raise ImportError("Install datasketch: pip install datasketch")
        return self._lsh

    def _make_minhash(self, text: str):
        try:
            from datasketch import MinHash
        except ImportError:
            raise ImportError("Install datasketch: pip install datasketch")

        tokens = _tokenize(text)
        shingles = _shingle(tokens)
        m = MinHash(num_perm=self.num_perm)
        for shingle in shingles:
            m.update(shingle.encode("utf-8"))
        return m

    def is_duplicate(self, item_id: str, text: str) -> bool:
        """
        Check if text is a near-duplicate of any previously seen item.

        Args:
            item_id: Unique ID for this item (used as LSH key)
            text:    Text content to check

        Returns:
            True if a near-duplicate exists, False otherwise.
        """
        lsh = self._get_lsh()
        minhash = self._make_minhash(text)

        result = lsh.query(minhash)
        if result:
            logger.debug(
                "deduplicator.near_duplicate_found",
                item_id=item_id,
                matches=result[:3],
            )
            return True

        # Add to index
        try:
            lsh.insert(item_id, minhash)
            self._seen_ids[item_id] = text[:100]
        except ValueError:
            # Key already inserted (shouldn't happen but handle gracefully)
            pass

        return False

    def filter_batch(
        self,
        items: list[tuple[str, str]],  # (item_id, text) pairs
    ) -> tuple[list[str], list[str]]:
        """
        Filter a batch of items, returning kept and removed IDs.

        Args:
            items: List of (item_id, text) tuples

        Returns:
            (kept_ids, removed_ids)
        """
        kept = []
        removed = []
        for item_id, text in items:
            if self.is_duplicate(item_id, text):
                removed.append(item_id)
            else:
                kept.append(item_id)

        logger.info(
            "deduplicator.batch_filtered",
            total=len(items),
            kept=len(kept),
            removed=len(removed),
        )
        return kept, removed

    def size(self) -> int:
        """Return the number of items in the deduplication index."""
        return len(self._seen_ids)

    def clear(self) -> None:
        """Reset the index (use between experiments)."""
        self._lsh = None
        self._seen_ids = {}
        self._initialized = False
        logger.info("deduplicator.cleared")

    def save(self, path: str | None = None) -> str:
        """
        Persist the MinHash LSH index and seen-ID map to disk using pickle.

        BUG FIX: The docstring referenced save()/load() but they were not
        implemented, so cross-batch deduplication was lost between pipeline
        runs. This implementation serialises both the LSH index and the
        seen-ID map so the full dedup state survives process restarts.

        Args:
            path: File path to write. Defaults to DEDUP_INDEX_PATH env var
                  or 'data/dedup_index.pkl'.

        Returns:
            Absolute path written.
        """
        import os
        import pickle

        save_path = path or os.environ.get("DEDUP_INDEX_PATH", "data/dedup_index.pkl")
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

        state = {
            "lsh": self._lsh,
            "seen_ids": self._seen_ids,
            "num_perm": self.num_perm,
            "threshold": self.threshold,
            "initialized": self._initialized,
        }
        with open(save_path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)

        logger.info("deduplicator.saved", path=save_path, size=len(self._seen_ids))
        return save_path

    def load(self, path: str | None = None) -> bool:
        """
        Load a previously saved MinHash LSH index from disk.

        Args:
            path: File path to read. Defaults to DEDUP_INDEX_PATH env var
                  or 'data/dedup_index.pkl'.

        Returns:
            True if loaded successfully, False if file does not exist.
        """
        import os
        import pickle

        load_path = path or os.environ.get("DEDUP_INDEX_PATH", "data/dedup_index.pkl")
        if not os.path.exists(load_path):
            logger.info("deduplicator.no_index_file", path=load_path)
            return False

        with open(load_path, "rb") as f:
            state = pickle.load(f)

        self._lsh = state["lsh"]
        self._seen_ids = state["seen_ids"]
        self.num_perm = state.get("num_perm", self.num_perm)
        self.threshold = state.get("threshold", self.threshold)
        self._initialized = state.get("initialized", True)

        logger.info("deduplicator.loaded", path=load_path, size=len(self._seen_ids))
        return True
