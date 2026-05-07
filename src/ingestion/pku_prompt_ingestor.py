"""Import PKU-SafeRLHF prompts as source material for AfriGuard adaptation."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from sqlalchemy.orm import Session

from src.storage.db import SourcePromptORM

logger = structlog.get_logger(__name__)

DEFAULT_PKU_DATASET = "PKU-Alignment/PKU-SafeRLHF"
DEFAULT_PKU_LICENSE = "CC-BY-NC-4.0"
DEFAULT_PKU_SOURCE_URL = "https://huggingface.co/datasets/PKU-Alignment/PKU-SafeRLHF"

_CATEGORY_KEYWORDS = {
    "H01": (
        "hate", "racist", "slur", "discrimin", "xenophob", "ethnic", "tribe",
        "religion", "bigot", "harass",
    ),
    "H02": (
        "rape", "sexual", "abuse", "assault", "coerc", "stalk", "groom", "domestic",
        "intimate", "violence against women",
    ),
    "H03": (
        "privacy", "personal data", "dox", "address", "phone", "password", "identity",
        "biometric", "surveillance", "private message",
    ),
    "H04": (
        "misinformation", "disinformation", "election", "vote", "voter", "rumor",
        "political", "campaign", "candidate", "ballot",
    ),
    "H05": (
        "fraud", "scam", "phishing", "money", "bank", "credit card", "loan",
        "investment", "crypto", "financial",
    ),
    "H06": (
        "child", "minor", "teen", "underage", "kid", "traffick", "child labor",
        "child marriage",
    ),
    "H07": (
        "suicide", "self-harm", "self harm", "depress", "anxiety", "gaslight",
        "manipulat", "emotional",
    ),
    "H08": (
        "medical", "medicine", "vaccine", "hiv", "aids", "cure", "doctor",
        "disease", "health", "treatment",
    ),
    "H09": (
        "terror", "extrem", "militia", "attack", "bomb", "armed", "recruit",
        "insurgent", "violence",
    ),
    "H10": (
        "weapon", "explosive", "bomb", "poison", "drug", "hack", "malware",
        "cybercrime", "bypass", "steal",
    ),
    "H11": (
        "safe", "helpful", "benign", "legal", "ethical", "advice", "support",
    ),
}

_RAW_CATEGORY_MAP = {
    "hate": "H01",
    "harassment": "H01",
    "sexual": "H02",
    "sex": "H02",
    "privacy": "H03",
    "misinformation": "H04",
    "disinformation": "H04",
    "fraud": "H05",
    "financial": "H05",
    "child": "H06",
    "self-harm": "H07",
    "self_harm": "H07",
    "medical": "H08",
    "violence": "H09",
    "extremism": "H09",
    "weapon": "H10",
    "cyber": "H10",
    "benign": "H11",
    "safe": "H11",
}


@dataclass(frozen=True)
class PKUIngestResult:
    inserted: int
    skipped: int
    seen: int


class PKUPromptIngestor:
    """Fetch and store PKU prompts for adaptation into AfriGuard prompts."""

    def ingest(
        self,
        session: Session,
        dataset_name: str = DEFAULT_PKU_DATASET,
        split: str = "train",
        prompt_column: str = "prompt",
        max_samples: int | None = None,
        license_name: str = DEFAULT_PKU_LICENSE,
        source_url: str = DEFAULT_PKU_SOURCE_URL,
        hf_config: str | None = None,
    ) -> PKUIngestResult:
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError("Install the 'datasets' package: pip install datasets") from exc

        logger.info(
            "pku_prompt_ingestor.loading",
            dataset=dataset_name,
            split=split,
            max_samples=max_samples,
        )
        load_args: tuple[str, ...] = (dataset_name, hf_config) if hf_config else (dataset_name,)
        dataset = load_dataset(*load_args, split=split)
        if max_samples and len(dataset) > max_samples:
            dataset = dataset.select(range(max_samples))

        inserted = 0
        skipped = 0
        seen = 0
        now = datetime.now(tz=timezone.utc)
        for index, row in enumerate(dataset):
            seen += 1
            prompt_text = _extract_prompt_text(row, prompt_column)
            if not prompt_text:
                skipped += 1
                continue

            source_prompt_id = _extract_source_id(row, index)
            provenance_hash = _hash_source_prompt(dataset_name, split, prompt_text)
            exists = (
                session.query(SourcePromptORM.id)
                .filter(SourcePromptORM.provenance_hash == provenance_hash)
                .first()
            )
            if exists:
                skipped += 1
                continue

            raw_category = _first_present(
                row,
                ("harm_category", "category", "prompt_type", "risk_category", "safety_category"),
            )
            raw_severity = _first_present(row, ("severity", "risk_level", "harm_severity"))
            mapped_category = _map_harm_category(raw_category, prompt_text)
            mapped_severity = _map_severity(raw_severity)

            metadata = {
                key: _jsonable(value)
                for key, value in dict(row).items()
                if key != prompt_column
            }
            session.add(
                SourcePromptORM(
                    id=str(uuid.uuid4()),
                    source_dataset=dataset_name,
                    source_split=split,
                    source_prompt_id=source_prompt_id,
                    prompt_text=prompt_text,
                    raw_harm_category=str(raw_category) if raw_category is not None else None,
                    mapped_harm_category=mapped_category,
                    raw_severity=str(raw_severity) if raw_severity is not None else None,
                    mapped_severity=mapped_severity,
                    metadata_=metadata,
                    license=license_name,
                    source_url=source_url,
                    provenance_hash=provenance_hash,
                    fetched_at=now,
                )
            )
            inserted += 1

        session.commit()
        logger.info(
            "pku_prompt_ingestor.done",
            dataset=dataset_name,
            split=split,
            inserted=inserted,
            skipped=skipped,
            seen=seen,
        )
        return PKUIngestResult(inserted=inserted, skipped=skipped, seen=seen)


def _extract_prompt_text(row: dict[str, Any], prompt_column: str) -> str:
    for column in (prompt_column, "prompt", "instruction", "question", "input"):
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _extract_source_id(row: dict[str, Any], index: int) -> str:
    for column in ("id", "prompt_id", "sample_id", "idx"):
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip()
    return str(index)


def _first_present(row: dict[str, Any], columns: Iterable[str]) -> Any:
    for column in columns:
        value = row.get(column)
        if value is not None and str(value).strip():
            return value
    return None


def _hash_source_prompt(dataset_name: str, split: str, prompt_text: str) -> str:
    raw = f"{dataset_name}::{split}::{prompt_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _map_harm_category(raw_category: Any, prompt_text: str) -> str | None:
    raw = str(raw_category or "").lower()
    for needle, mapped in _RAW_CATEGORY_MAP.items():
        if needle in raw:
            return mapped

    lowered = prompt_text.lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword in lowered)
        for category, keywords in _CATEGORY_KEYWORDS.items()
    }
    best_category, best_score = max(scores.items(), key=lambda item: item[1])
    return best_category if best_score > 0 else None


def _map_severity(raw_severity: Any) -> str | None:
    if raw_severity is None:
        return None
    raw = str(raw_severity).strip().lower()
    if raw in {"s1", "1", "low", "mild"}:
        return "S1"
    if raw in {"s2", "2", "medium", "moderate"}:
        return "S2"
    if raw in {"s3", "3", "high", "severe"}:
        return "S3"
    if raw in {"s4", "4", "critical", "extreme"}:
        return "S4"
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return str(value)
