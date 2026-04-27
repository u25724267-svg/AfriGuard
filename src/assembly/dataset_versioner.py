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
        release_dir = _DATA_DIR / "releases" / version
        release_dir.mkdir(parents=True, exist_ok=True)

        query = session.query(DatasetItemORM).filter(
            DatasetItemORM.dataset_version == version
        )
        if language:
            query = query.filter(DatasetItemORM.language == language)

        items = query.all()
        logger.info(
            "dataset_versioner.exporting",
            version=version,
            total_items=len(items),
        )

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

        # Write dataset card
        card = self._build_dataset_card(version, items, item_counts)
        card_path = release_dir / "dataset_card.json"
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)

        logger.info(
            "dataset_versioner.export_complete",
            version=version,
            release_dir=str(release_dir),
            total_items=len(items),
        )
        return release_dir

    def _write_jsonl(self, path: Path, items: list[DatasetItemORM]) -> None:
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

    def _build_dataset_card(
        self,
        version: str,
        items: list[DatasetItemORM],
        item_counts: dict[str, int],
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
            "languages": list(by_language.keys()),
            "harm_categories": [f"H0{i}" if i < 10 else f"H{i}" for i in range(1, 12)],
            "total_items": len(items),
            "items_by_language": by_language,
            "items_by_type": by_type,
            "item_counts_detail": item_counts,
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
