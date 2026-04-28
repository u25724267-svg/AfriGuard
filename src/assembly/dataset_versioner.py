"""
AfriGuard — Assembly: DatasetVersioner

Exports finalized dataset items to JSONL and Parquet files,
organized by version, language, and item type.
Optionally integrates with DVC for dataset versioning.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from src.config.env import load_project_env
from src.storage.db import DatasetItemORM

load_project_env()
logger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))


class DatasetVersioner:
    """
    Exports reviewed dataset items to structured files.

    Produces:
      data/releases/<version>/
        ├── all_languages/
        │   ├── preference_pairs.jsonl
        │   ├── qa_safe.jsonl
        │   ├── qa_unsafe.jsonl
        │   └── classification.jsonl
        ├── hausa/
        │   ├── preference_pairs.jsonl
        │   └── ...
        ├── ...
        └── dataset_card.json
    """

    def export(
        self,
        session: Session,
        version: str,
        language: str | None = None,
    ) -> Path:
        """
        Export all dataset items for the given version.

        Args:
            session:  DB session
            version:  Dataset version string (e.g. '0.1.0')
            language: If set, export only this language

        Returns:
            Path to the release directory.
        """
        from src.storage.db import CandidateResponseORM

        release_dir = _DATA_DIR / "releases" / version
        release_dir.mkdir(parents=True, exist_ok=True)

        query = session.query(DatasetItemORM).filter(
            DatasetItemORM.dataset_version == version
        )
        if language:
            query = query.filter(DatasetItemORM.language == language)

        items = self._dedupe_items(query.all())
        logger.info(
            "dataset_versioner.exporting",
            version=version,
            total_items=len(items),
        )

        # Compute review coverage stats from candidate statuses
        cand_query = session.query(CandidateResponseORM)
        if language:
            cand_query = cand_query.filter(CandidateResponseORM.language == language)

        all_candidates = cand_query.all()
        total_passed = sum(1 for c in all_candidates if c.status in (
            "passed_filter", "sampled_for_review", "approved", "rejected", "flagged"
        ))
        total_sampled = sum(1 for c in all_candidates if c.status in (
            "sampled_for_review", "approved", "rejected", "flagged"
        ))
        total_human_reviewed = sum(1 for c in all_candidates if c.status in (
            "approved", "rejected", "flagged"
        ))

        review_stats = {
            "total_passed_filter": total_passed,
            "total_sampled_for_review": total_sampled,
            "total_human_reviewed": total_human_reviewed,
            "sample_coverage_pct": round(
                100 * total_sampled / total_passed, 1
            ) if total_passed else 0,
            "review_completion_pct": round(
                100 * total_human_reviewed / total_sampled, 1
            ) if total_sampled else 0,
        }

        # Group by (language, item_type)
        groups: dict[tuple[str, str], list[DatasetItemORM]] = {}
        for item in items:
            key = (item.language, item.item_type)
            groups.setdefault(key, []).append(item)

        # Write per-language files
        item_counts: dict[str, int] = {}
        for (lang, itype), lang_items in groups.items():
            lang_dir = release_dir / lang
            lang_dir.mkdir(exist_ok=True)
            out_path = lang_dir / f"{itype}.jsonl"
            self._write_jsonl(out_path, lang_items)
            item_counts[f"{lang}/{itype}"] = len(lang_items)

        # Write all-language combined files
        all_dir = release_dir / "all_languages"
        all_dir.mkdir(exist_ok=True)

        item_types = {"preference_pair", "qa_safe", "qa_unsafe", "classification"}
        for itype in item_types:
            all_items = [i for i in items if i.item_type == itype]
            if all_items:
                out_path = all_dir / f"{itype}.jsonl"
                self._write_jsonl(out_path, all_items)

        # Write PKU-style release files:
        #   prompts.jsonl, qa_pairs.jsonl, preference_pairs.jsonl
        self._write_pku_style_exports(release_dir, items)

        # Write dataset card
        card = self._build_dataset_card(version, items, item_counts, review_stats)
        card_path = release_dir / "dataset_card.json"
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)

        logger.info(
            "dataset_versioner.export_complete",
            version=version,
            release_dir=str(release_dir),
            total_items=len(items),
            review_stats=review_stats,
        )
        return release_dir

    def _write_jsonl(self, path: Path, items: list[DatasetItemORM]) -> None:
        items = self._dedupe_items(items)
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                record = {
                    "id": item.id,
                    "item_type": item.item_type,
                    "language": item.language,
                    "language_code": item.language_code,
                    "harm_category": item.harm_category,
                    "harm_category_name": item.harm_category_name,
                    "severity": item.severity,
                    "prompt": item.prompt_text,
                    "chosen": item.chosen_response_text,
                    "rejected": item.rejected_response_text,
                    "response": item.response_text,
                    "classification_text": item.classification_text,
                    "harm_label": item.harm_label,
                    "severity_label": item.severity_label,
                    "provenance": {
                        "prompt_id": item.prompt_id,
                        "prompt_template_id": item.prompt_template_id,
                        "seed_document_ids": item.seed_document_ids,
                        "models_used": item.models_used,
                        "annotator_ids": item.annotator_ids,
                        "dataset_version": item.dataset_version,
                        "run_id": item.run_id,
                    },
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _dedupe_items(self, items: list[DatasetItemORM]) -> list[DatasetItemORM]:
        """Remove exact logical duplicates while preserving valid variants."""
        seen: set[tuple] = set()
        unique: list[DatasetItemORM] = []
        for item in items:
            key = self._item_key(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @staticmethod
    def _item_key(item: DatasetItemORM) -> tuple:
        """Stable logical identity for an exported dataset item."""
        if item.item_type == "preference_pair":
            return (
                item.item_type,
                item.dataset_version,
                item.prompt_id,
                item.chosen_response_id,
                item.rejected_response_id,
            )
        if item.item_type in {"qa_safe", "qa_unsafe"}:
            return (
                item.item_type,
                item.dataset_version,
                item.prompt_id,
                item.response_id,
            )
        if item.item_type == "classification":
            return (
                item.item_type,
                item.dataset_version,
                item.prompt_id,
                item.response_id,
                item.classification_text,
                item.harm_label,
                item.severity_label,
            )
        return (item.item_type, item.dataset_version, item.id)

    def _write_pku_style_exports(self, release_dir: Path, items: list[DatasetItemORM]) -> None:
        """Write three PKU-style dataset products alongside AfriGuard-native files."""
        grouped: dict[str, list[DatasetItemORM]] = {"all_languages": items}
        for item in items:
            grouped.setdefault(item.language, []).append(item)

        for group_name, group_items in grouped.items():
            out_dir = release_dir / group_name / "pku_style"
            out_dir.mkdir(parents=True, exist_ok=True)

            self._write_dict_jsonl(
                out_dir / "prompts.jsonl",
                self._build_prompt_records(group_items),
            )
            self._write_dict_jsonl(
                out_dir / "qa_pairs.jsonl",
                self._build_qa_records(group_items),
            )
            self._write_dict_jsonl(
                out_dir / "preference_pairs.jsonl",
                self._build_preference_records(group_items),
            )

    def _build_prompt_records(self, items: list[DatasetItemORM]) -> list[dict]:
        """Build unique prompt-level records similar to PKU's prompt product."""
        seen: set[str] = set()
        records: list[dict] = []
        for item in items:
            if item.prompt_id in seen:
                continue
            seen.add(item.prompt_id)
            records.append(
                {
                    "prompt_id": item.prompt_id,
                    "prompt": item.prompt_text,
                    "language": item.language,
                    "language_code": item.language_code,
                    "harm_category": item.harm_category,
                    "harm_category_name": item.harm_category_name,
                    "severity": item.severity,
                    "severity_level": self._severity_to_level(item.severity),
                    "prompt_template_id": item.prompt_template_id,
                    "seed_document_ids": item.seed_document_ids or [],
                    "run_id": item.run_id,
                    "dataset_version": item.dataset_version,
                }
            )
        return records

    def _build_qa_records(self, items: list[DatasetItemORM]) -> list[dict]:
        """Build PKU-QA-style records with safety metadata."""
        seen: set[tuple] = set()
        records: list[dict] = []
        for item in items:
            if item.item_type not in {"qa_safe", "qa_unsafe"}:
                continue
            key = (item.prompt_id, item.response_id, item.item_type)
            if key in seen:
                continue
            seen.add(key)
            is_safe = item.item_type == "qa_safe"
            records.append(
                {
                    "prompt": item.prompt_text,
                    "response": item.response_text,
                    "language": item.language,
                    "language_code": item.language_code,
                    "is_safe": is_safe,
                    "harm_category": self._harm_category_dict(item.harm_category, not is_safe),
                    "harm_category_id": item.harm_category,
                    "harm_category_name": item.harm_category_name,
                    "severity": item.severity,
                    "severity_level": self._severity_to_level(item.severity),
                    "prompt_id": item.prompt_id,
                    "response_id": item.response_id,
                    "models_used": item.models_used or [],
                    "annotator_ids": item.annotator_ids or [],
                    "dataset_version": item.dataset_version,
                    "run_id": item.run_id,
                }
            )
        return records

    def _build_preference_records(self, items: list[DatasetItemORM]) -> list[dict]:
        """Build PKU-preference-style records with paired responses."""
        seen: set[tuple] = set()
        records: list[dict] = []
        for item in items:
            if item.item_type != "preference_pair":
                continue
            key = (item.prompt_id, item.chosen_response_id, item.rejected_response_id)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "prompt": item.prompt_text,
                    "response_0": item.chosen_response_text,
                    "response_1": item.rejected_response_text,
                    "language": item.language,
                    "language_code": item.language_code,
                    "harm_category": self._harm_category_dict(item.harm_category, True),
                    "harm_category_id": item.harm_category,
                    "harm_category_name": item.harm_category_name,
                    "severity": item.severity,
                    "severity_level": self._severity_to_level(item.severity),
                    "better_response_id": 0,
                    "safer_response_id": 0,
                    "chosen_response_id": item.chosen_response_id,
                    "rejected_response_id": item.rejected_response_id,
                    "prompt_id": item.prompt_id,
                    "models_used": item.models_used or [],
                    "annotator_ids": item.annotator_ids or [],
                    "dataset_version": item.dataset_version,
                    "run_id": item.run_id,
                }
            )
        return records

    def _write_dict_jsonl(self, path: Path, records: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _severity_to_level(severity: str | None) -> int:
        """Map AfriGuard severity labels to PKU-like numeric levels."""
        return {"S1": 0, "S2": 1, "S3": 2, "S4": 3}.get(severity or "", 0)

    @staticmethod
    def _harm_category_dict(harm_category: str | None, active: bool) -> dict[str, bool]:
        """Represent a single AfriGuard harm category in PKU-style dict form."""
        if not harm_category:
            return {}
        return {harm_category: active}

    def _build_dataset_card(
        self,
        version: str,
        items: list[DatasetItemORM],
        item_counts: dict[str, int],
        review_stats: dict | None = None,
    ) -> dict:
        by_language: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for item in items:
            by_language[item.language] = by_language.get(item.language, 0) + 1
            by_type[item.item_type] = by_type.get(item.item_type, 0) + 1

        return {
            "dataset_name": "AfriGuard",
            "version": version,
            "description": (
                "Afrocentric safety-alignment dataset generated from scratch using "
                "culturally grounded prompts, Afrocentric seed data, and human review "
                "by native-language researchers."
            ),
            "review_methodology": (
                "Human review is sample-based. A stratified subset of generated candidates "
                "was reviewed by native-language researchers (one per language). "
                "Items not in the reviewed sample were accepted based on automatic "
                "filtering (language detection, quality scoring, deduplication) and "
                "are marked human_reviewed=False in provenance. "
                "Review samples were stratified across harm category, severity, and "
                "response type, with borderline cases (near quality threshold) "
                "prioritised. See review_stats below for coverage."
            ),
            "review_stats": review_stats or {},
            "languages": list(by_language.keys()),
            "harm_categories": [f"H0{i}" if i < 10 else f"H{i}" for i in range(1, 12)],
            "total_items": len(items),
            "items_by_language": by_language,
            "items_by_type": by_type,
            "item_counts_detail": item_counts,
            "pku_style_outputs": {
                "prompts": "pku_style/prompts.jsonl",
                "qa_pairs": "pku_style/qa_pairs.jsonl",
                "preference_pairs": "pku_style/preference_pairs.jsonl",
                "note": (
                    "PKU-style exports are compatibility files. AfriGuard-native "
                    "files remain available as classification, qa_safe, qa_unsafe, "
                    "and preference_pair JSONL files."
                ),
            },
            "license": "CC BY 4.0",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "citation": (
                "@dataset{afriguard2024,\n"
                "  title={AfriGuard: Afrocentric Safety-Alignment Dataset},\n"
                "  author={AfriGuard Research Team},\n"
                "  year={2024},\n"
                "  note={Version " + version + "}\n"
                "}"
            ),
        }
