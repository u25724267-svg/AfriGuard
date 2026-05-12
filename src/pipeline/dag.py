"""
AfriGuard — Pipeline: CLI DAG

Entry point for all pipeline stages. Run stages independently or as a full pipeline.

Usage:
  afriguard bootstrap-db
  afriguard ingest-seeds [--language hausa] [--max-samples 500]
  afriguard generate [--language hausa] [--category H01] [--severity S2] [--n-prompts 10]
  afriguard filter [--language hausa]
  afriguard assign-review
  afriguard assemble [--version 0.1.0]
  afriguard export [--version 0.1.0]
  afriguard run-all [--language hausa] [--resume] [--run-id <id>]
  afriguard resume-status [--run-id <id>]
  afriguard review-ui
  afriguard cost-report
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import click
import structlog

from src.config.env import load_project_env
from src.observability.logging_config import configure_logging

load_project_env()
configure_logging()
logger = structlog.get_logger(__name__)


@contextmanager
def _temporary_log_levels(levels: dict[str, int]):
    previous = {}
    for name, level in levels.items():
        log = logging.getLogger(name)
        previous[name] = log.level
        log.setLevel(level)
    try:
        yield
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)


_QUIET_GENERATION_LOGGERS = {
    "src.generation.generation_job": logging.WARNING,
    "src.generation.pku_adapted_generation_job": logging.WARNING,
    "src.generation.cost_tracker": logging.WARNING,
    "src.prompt_construction.prompt_version_store": logging.WARNING,
    "src.taxonomy.harm_registry": logging.WARNING,
    "src.taxonomy.entity_sampler": logging.WARNING,
    "src.prompt_construction.seed_context_injector": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "openai": logging.WARNING,
}


def _generation_mode(params) -> str:
    if isinstance(params, dict):
        return params.get("generation_mode", "native")
    return "native"


def _normalize_prompt_generation_mode(mode: str) -> str:
    aliases = {
        "native": "native",
        "pku-adapted": "pku_context_regeneration",
        "pku_adapted": "pku_context_regeneration",
        "pku-context": "pku_context_regeneration",
        "pku-context-regeneration": "pku_context_regeneration",
        "pku_context_regeneration": "pku_context_regeneration",
    }
    return aliases.get(mode, mode)


def _prompt_pipeline_name(generation_mode: str) -> str:
    if generation_mode == "native":
        return "native_prompt_only"
    return "pku_context_regeneration_prompt_only"


def _matches_prompt_only_generation_mode(params, generation_mode: str) -> bool:
    if not isinstance(params, dict):
        return False
    mode = _generation_mode(params)
    if generation_mode == "native":
        return mode == "native" and (
            params.get("prompt_pipeline") == "native_prompt_only"
            or params.get("prompt_only") is True
        )
    return mode in {"pku_context_regeneration", "pku_adapted"} and (
        params.get("prompt_pipeline") == "pku_context_regeneration_prompt_only"
        or params.get("prompt_only") is True
        or ("prompt_pipeline" not in params and "prompt_only" not in params)
    )


def _validate_run_id(run_id: str) -> str:
    if len(run_id) > 36:
        raise click.ClickException(
            f"--run-id must be 36 characters or fewer; got {len(run_id)}. "
            "Use a shorter label or omit --run-id to let AfriGuard generate a UUID."
        )
    return run_id

# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """AfriGuard — Afrocentric Safety-Alignment Data Pipeline"""
    pass


# ---------------------------------------------------------------------------
# bootstrap-db
# ---------------------------------------------------------------------------

@cli.command("bootstrap-db")
def bootstrap_db():
    """Initialize (or migrate) the database schema."""
    from src.storage.db import init_db
    init_db()
    click.secho("[OK] Database initialized.", fg="green")


# ---------------------------------------------------------------------------
# ingest-seeds
# ---------------------------------------------------------------------------

@cli.command("ingest-seeds")
@click.option("--language", "-l", default=None, help="Only ingest seeds for this language")
@click.option("--max-samples", default=500, show_default=True, help="Max records per source")
@click.option("--source-ids", default=None, help="Comma-separated source IDs to ingest")
def ingest_seeds(language, max_samples, source_ids):
    """Fetch and store Afrocentric seed datasets."""
    from src.storage.db import SessionLocal
    from src.ingestion.seed_fetcher import SeedFetcher
    from src.ingestion.seed_normalizer import SeedNormalizer
    from src.ingestion.seed_store import SeedStore

    fetcher = SeedFetcher()
    normalizer = SeedNormalizer()
    store = SeedStore()

    languages = [language] if language else None
    src_ids = [s.strip() for s in source_ids.split(",")] if source_ids else None

    click.echo(f"[IN] Fetching seed data (max_samples={max_samples})…")
    batches = fetcher.fetch_all(
        max_samples_per_source=max_samples,
        languages=languages,
        source_ids=src_ids,
    )

    total_inserted = 0
    total_skipped = 0

    with SessionLocal() as session:
        for source_config, records in batches:
            if not records:
                continue
            docs, skipped = normalizer.normalize(
                source_config,
                records,
                target_language=language,
            )
            inserted, dup_skipped = store.save_batch(docs, session)
            total_inserted += inserted
            total_skipped += skipped + dup_skipped
            click.echo(
                f"  [{source_config.get('id')}] {inserted} inserted, "
                f"{skipped + dup_skipped} skipped"
            )

        counts = store.count(session)

    click.echo("\n[##] Seed document counts by language:")
    for lang, count in sorted(counts.items()):
        click.echo(f"  {lang}: {count}")

    click.secho(
        f"\n[OK] Done. Total inserted: {total_inserted}, skipped: {total_skipped}", fg="green"
    )


# ---------------------------------------------------------------------------
# ingest-pku-prompts
# ---------------------------------------------------------------------------

@cli.command("ingest-pku-prompts")
@click.option("--dataset", default="PKU-Alignment/PKU-SafeRLHF", show_default=True)
@click.option("--split", default="train", show_default=True)
@click.option("--hf-config", default=None, help="Optional Hugging Face dataset config/name")
@click.option("--prompt-column", default="prompt", show_default=True)
@click.option("--max-samples", default=1000, show_default=True, help="Max PKU rows to import")
def ingest_pku_prompts(dataset, split, hf_config, prompt_column, max_samples):
    """Import PKU prompts as source material for pku-adapted generation."""
    from src.storage.db import SessionLocal, init_db
    from src.ingestion.pku_prompt_ingestor import (
        DEFAULT_PKU_LICENSE,
        DEFAULT_PKU_SOURCE_URL,
        PKUPromptIngestor,
    )

    init_db()
    click.echo(
        f"[IN] Importing PKU source prompts from {dataset} split={split} "
        f"(max_samples={max_samples})..."
    )
    with SessionLocal() as session:
        result = PKUPromptIngestor().ingest(
            session=session,
            dataset_name=dataset,
            split=split,
            hf_config=hf_config,
            prompt_column=prompt_column,
            max_samples=max_samples,
            license_name=DEFAULT_PKU_LICENSE,
            source_url=(
                DEFAULT_PKU_SOURCE_URL
                if dataset == "PKU-Alignment/PKU-SafeRLHF"
                else f"https://huggingface.co/datasets/{dataset}"
            ),
        )

    click.secho(
        f"[OK] PKU source prompts imported: {result.inserted} inserted, "
        f"{result.skipped} skipped, {result.seen} seen.",
        fg="green",
    )


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

@cli.command("generate")
@click.option("--language", "-l", default=None, help="Target language (all if not set)")
@click.option("--category", "-c", default=None, help="Harm category ID (e.g. H01)")
@click.option("--severity", "-s", default=None, help="Severity code (S1-S4)")
@click.option("--n-prompts", "-n", default=5, show_default=True, help="Prompts per combination")
@click.option("--model", default=None, help="Override default model (e.g. gpt-5.4)")
@click.option(
    "--generation-mode",
    type=click.Choice(["native", "pku-adapted"]),
    default="native",
    show_default=True,
    help="Prompt generation strategy",
)
@click.option("--pku-dataset", default=None, help="Restrict pku-adapted source prompts to this dataset")
@click.option("--run-id", default=None, help="Reuse an existing pipeline run ID")
@click.option("--progress/--no-progress", default=True, help="Show generation progress bar")
@click.option("--dry-run", is_flag=True, help="Print config without calling API")
def generate(
    language,
    category,
    severity,
    n_prompts,
    model,
    generation_mode,
    pku_dataset,
    run_id,
    progress,
    dry_run,
):
    """Generate prompts and candidate responses using LLM."""
    import yaml
    from pathlib import Path
    from src.config.generation import load_generation_config
    from src.config.languages import list_language_names

    generation_config = load_generation_config()
    config_path = Path(__file__).parent.parent.parent / "configs" / "pipeline.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    model_id = model or generation_config.default_model
    languages = [language] if language else list_language_names()
    categories = [category] if category else config["active_harm_categories"]
    severities = [severity] if severity else ["S1", "S2", "S3", "S4"]

    poc_max = int(os.environ.get("POC_MAX_ITEMS_PER_LANGUAGE", config["pipeline"]["poc_max_items_per_language"]))
    n_candidates = generation_config.candidates_per_prompt

    total_combinations = len(languages) * len(categories) * len(severities)
    click.echo(
        f"[>>] Generation plan: {len(languages)} languages × {len(categories)} categories "
        f"× {len(severities)} severities = {total_combinations} combinations\n"
        f"   {n_prompts} prompts × {n_candidates} candidates each = "
        f"{total_combinations * n_prompts * n_candidates} total candidates\n"
        f"   Model: {model_id}\n"
        f"   Generation mode: {generation_mode}"
    )

    if dry_run:
        click.secho("[?] Dry run — no API calls made.", fg="yellow")
        for lang in languages:
            for cat in categories:
                for sev in severities:
                    click.echo(f"  Would generate: {lang} / {cat} / {sev}")
        return

    from sqlalchemy import func
    from src.storage.db import (
        SessionLocal,
        GeneratedPromptORM,
        GenerationCostORM,
        PipelineRunORM,
        PipelineStageRunORM,
        SourcePromptORM,
        init_db,
    )
    from src.generation.generation_job import GenerationJob
    from src.generation.pku_adapted_generation_job import PKUAdaptedGenerationJob
    from tqdm import tqdm

    init_db()
    run_id = run_id or str(uuid.uuid4())
    run_id = _validate_run_id(run_id)
    total_target_prompts = len(languages) * len(categories) * len(severities) * n_prompts
    click.echo(f"   Run ID: {run_id}\n")

    with SessionLocal() as session:
        if generation_mode == "pku-adapted":
            source_query = session.query(func.count(SourcePromptORM.id))
            if pku_dataset:
                source_query = source_query.filter(SourcePromptORM.source_dataset == pku_dataset)
            source_count = int(source_query.scalar() or 0)
            if source_count == 0:
                raise click.ClickException(
                    "No PKU source prompts found. Run `afriguard ingest-pku-prompts` first."
                )
            click.echo(f"   PKU source prompts available: {source_count}\n")

        work_items = []
        total_existing = 0
        total_remaining = 0
        for lang in languages:
            for cat in categories:
                for sev in severities:
                    existing_rows = (
                        session.query(GeneratedPromptORM.generation_params)
                        .filter(
                            GeneratedPromptORM.run_id == run_id,
                            GeneratedPromptORM.language == lang,
                            GeneratedPromptORM.harm_category == cat,
                            GeneratedPromptORM.severity == sev,
                            GeneratedPromptORM.status == "generated",
                        )
                        .all()
                    )
                    existing = sum(
                        1
                        for (params,) in existing_rows
                        if _generation_mode(params) == generation_mode
                    )
                    remaining = max(0, n_prompts - existing)
                    total_existing += min(existing, n_prompts)
                    total_remaining += remaining
                    work_items.append((lang, cat, sev, existing, remaining))

        total_prompts = total_existing + total_remaining
        bar = tqdm(
            total=total_prompts,
            initial=total_existing,
            desc="Generating prompts",
            unit="prompt",
            dynamic_ncols=True,
            disable=not progress,
        )
        write_status = tqdm.write if progress else click.echo

        def update_progress(lang: str, cat: str, sev: str):
            bar.update(1)
            total_cost, api_calls = (
                session.query(
                    func.coalesce(func.sum(GenerationCostORM.cost_usd), 0.0),
                    func.count(GenerationCostORM.id),
                )
                .filter(GenerationCostORM.run_id == run_id)
                .one()
            )
            bar.set_postfix(
                {
                    "lang": lang,
                    "cat": cat,
                    "sev": sev,
                    "model": model_id,
                    "cost": f"${float(total_cost):.2f}",
                    "api": int(api_calls),
                },
                refresh=True,
            )

        try:
            quiet_context = (
                _temporary_log_levels(_QUIET_GENERATION_LOGGERS)
                if progress
                else _temporary_log_levels({})
            )
            with quiet_context:
                for lang, cat, sev, existing, remaining in work_items:
                    if remaining == 0:
                        continue

                    bar.set_postfix(
                        {
                            "lang": lang,
                            "cat": cat,
                            "sev": sev,
                            "model": model_id,
                        },
                        refresh=True,
                    )
                    try:
                        if generation_mode == "pku-adapted":
                            job = PKUAdaptedGenerationJob(
                                language=lang,
                                harm_category=cat,
                                severity=sev,
                                model_id=model_id,
                                n_candidates=n_candidates,
                                run_id=run_id,
                                source_dataset=pku_dataset,
                            )
                        else:
                            job = GenerationJob(
                                language=lang,
                                harm_category=cat,
                                severity=sev,
                                model_id=model_id,
                                n_candidates=n_candidates,
                                run_id=run_id,
                            )
                        job.run(
                            session=session,
                            n_prompts=remaining,
                            progress_callback=lambda _prompt_id, lang=lang, cat=cat, sev=sev: update_progress(
                                lang, cat, sev
                            ),
                        )
                    except Exception as e:
                        write_status(f"  [-] {lang} / {cat} / {sev}: {e}")
        finally:
            bar.close()

    click.secho(f"\n[OK] Generation complete. Run ID: {run_id}", fg="green")


# ---------------------------------------------------------------------------
# generate-prompts
# ---------------------------------------------------------------------------

@cli.command("generate-prompts")
@click.option("--language", "-l", default=None, help="Target language (all if not set)")
@click.option("--tier", default=None, help="Target language tier from configs/target_languages.yaml, e.g. tier_1")
@click.option("--category", "-c", default=None, help="Harm category ID (e.g. H01)")
@click.option("--severity", "-s", default=None, help="Severity code (S1-S4)")
@click.option("--n-prompts", "-n", default=5, show_default=True, help="Prompts per combination")
@click.option("--model", default=None, help="Override default prompt model")
@click.option(
    "--generation-mode",
    type=click.Choice(["pku-context-regeneration", "pku-context", "pku-adapted", "native"]),
    default="pku-context-regeneration",
    show_default=True,
    help="Prompt-only generation strategy",
)
@click.option("--pku-dataset", default=None, help="Restrict PKU source prompts to this dataset")
@click.option("--run-id", default=None, help="Reuse an existing pipeline run ID")
@click.option("--workers", default=1, show_default=True, type=int, help="Parallel worker count")
@click.option("--dry-run", is_flag=True, help="Print config without calling API")
def generate_prompts(
    language,
    tier,
    category,
    severity,
    n_prompts,
    model,
    generation_mode,
    pku_dataset,
    run_id,
    workers,
    dry_run,
):
    """Generate prompt-only data; responses are batched later."""
    import yaml
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path
    from threading import Lock
    from sqlalchemy import func
    from tqdm import tqdm

    from src.config.generation import load_generation_config
    from src.config.languages import list_language_names
    from src.storage.db import (
        SessionLocal,
        GeneratedPromptORM,
        GenerationCostORM,
        PipelineRunORM,
        PipelineStageRunORM,
        SourcePromptORM,
        init_db,
    )
    from src.generation.generation_job import GenerationJob
    from src.generation.pku_adapted_generation_job import PKUAdaptedGenerationJob

    if workers < 1:
        raise click.ClickException("--workers must be at least 1")
    prompt_generation_mode = _normalize_prompt_generation_mode(generation_mode)
    prompt_pipeline = _prompt_pipeline_name(prompt_generation_mode)
    if prompt_generation_mode == "native" and pku_dataset:
        raise click.ClickException("--pku-dataset is only valid with PKU-context generation modes.")

    generation_config = load_generation_config()
    config_path = Path(__file__).parent.parent.parent / "configs" / "pipeline.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if language and tier:
        raise click.ClickException("Use either --language or --tier, not both.")

    model_id = model or generation_config.default_model
    configured_languages = set(list_language_names())
    if tier:
        target_path = Path(__file__).parent.parent.parent / "configs" / "target_languages.yaml"
        with open(target_path, encoding="utf-8") as f:
            target_config = yaml.safe_load(f) or {}
        tier_config = next(
            (row for row in target_config.get("tiers", []) if row.get("id") == tier),
            None,
        )
        if tier_config is None and tier in {"all", "afriguard_40", "afriguard_40_v1"}:
            languages = [
                row["name"]
                for tier_row in target_config.get("tiers", [])
                for row in tier_row.get("languages", [])
            ]
        elif tier_config is None:
            known = ", ".join(row.get("id", "") for row in target_config.get("tiers", []))
            raise click.ClickException(f"Unknown tier: {tier}. Known tiers: {known}, all")
        else:
            languages = [row["name"] for row in tier_config.get("languages", [])]
        unsupported = [lang for lang in languages if lang not in configured_languages]
        if unsupported:
            raise click.ClickException(
                "Tier contains languages not yet in configs/languages.yaml: "
                + ", ".join(unsupported)
            )
    else:
        languages = [language] if language else list_language_names()
    categories = [category] if category else config["active_harm_categories"]
    severities = [severity] if severity else ["S1", "S2", "S3", "S4"]
    run_id = run_id or str(uuid.uuid4())
    run_id = _validate_run_id(run_id)

    total_combinations = len(languages) * len(categories) * len(severities)
    total_target_prompts = total_combinations * n_prompts
    click.echo(
        f"[>>] Prompt-only plan: {len(languages)} languages × {len(categories)} categories "
        f"× {len(severities)} severities = {total_combinations} combinations\n"
        f"   {n_prompts} prompts per combination\n"
        f"   Method: {prompt_generation_mode}\n"
        f"   Prompt pipeline: {prompt_pipeline}\n"
        f"   Model: {model_id}\n"
        f"   Workers: {workers}\n"
        f"   Run ID: {run_id}"
    )

    if dry_run:
        click.secho("[?] Dry run — no API calls made.", fg="yellow")
        return

    init_db()
    with SessionLocal() as session:
        now = datetime.now(tz=timezone.utc)
        monitor_run = session.get(PipelineRunORM, run_id)
        if monitor_run is None:
            monitor_run = PipelineRunORM(
                id=run_id,
                status="running",
                current_stage="generate_prompts",
                requested_language=language,
                n_prompts=n_prompts,
                metadata_={
                    "workflow": "prompt_first",
                    "command": "generate-prompts",
                    "tier": tier,
                    "languages": languages,
                    "categories": categories,
                    "severities": severities,
                    "target_prompt_count": total_target_prompts,
                    "generation_mode": prompt_generation_mode,
                    "prompt_pipeline": prompt_pipeline,
                    "response_strategy": "batch_response_generation",
                    "workers": workers,
                    "prompt_only": True,
                    "resume_enabled": True,
                },
                started_at=now,
                updated_at=now,
            )
            session.add(monitor_run)
        else:
            metadata = dict(monitor_run.metadata_ or {})
            metadata.update(
                {
                    "workflow": "prompt_first",
                    "command": "generate-prompts",
                    "tier": tier,
                    "languages": languages,
                    "categories": categories,
                    "severities": severities,
                    "target_prompt_count": total_target_prompts,
                    "generation_mode": prompt_generation_mode,
                    "prompt_pipeline": prompt_pipeline,
                    "response_strategy": "batch_response_generation",
                    "workers": workers,
                    "prompt_only": True,
                    "resume_enabled": True,
                }
            )
            monitor_run.status = "running"
            monitor_run.current_stage = "generate_prompts"
            monitor_run.requested_language = language
            monitor_run.n_prompts = n_prompts
            monitor_run.metadata_ = metadata
            monitor_run.updated_at = now

        stage = (
            session.query(PipelineStageRunORM)
            .filter(
                PipelineStageRunORM.run_id == run_id,
                PipelineStageRunORM.stage_name == "generate_prompts",
            )
            .first()
        )
        if stage is None:
            stage = PipelineStageRunORM(
                id=str(uuid.uuid4()),
                run_id=run_id,
                stage_name="generate_prompts",
                started_at=now,
            )
            session.add(stage)
        stage.status = "running"
        stage.error = None
        stage.updated_at = now
        stage.attempts = (stage.attempts or 0) + 1
        stage.metadata_ = {
            "tier": tier,
            "languages": languages,
            "categories": categories,
            "severities": severities,
            "target_prompt_count": total_target_prompts,
            "generation_mode": prompt_generation_mode,
            "prompt_pipeline": prompt_pipeline,
            "response_strategy": "batch_response_generation",
            "workers": workers,
        }
        session.commit()

        if prompt_generation_mode == "pku_context_regeneration":
            source_query = session.query(func.count(SourcePromptORM.id))
            if pku_dataset:
                source_query = source_query.filter(SourcePromptORM.source_dataset == pku_dataset)
            source_count = int(source_query.scalar() or 0)
            if source_count == 0:
                raise click.ClickException(
                    "No PKU source prompts found. Run `afriguard ingest-pku-prompts` first."
                )

        work_items = []
        total_existing = 0
        for lang in languages:
            for cat in categories:
                for sev in severities:
                    existing_rows = (
                        session.query(GeneratedPromptORM.generation_params)
                        .filter(
                            GeneratedPromptORM.run_id == run_id,
                            GeneratedPromptORM.language == lang,
                            GeneratedPromptORM.harm_category == cat,
                            GeneratedPromptORM.severity == sev,
                        )
                        .all()
                    )
                    existing = sum(
                        1
                        for (params,) in existing_rows
                        if _matches_prompt_only_generation_mode(params, prompt_generation_mode)
                    )
                    remaining = max(0, n_prompts - existing)
                    total_existing += min(existing, n_prompts)
                    if remaining:
                        work_items.append((lang, cat, sev, remaining))

    progress_lock = Lock()

    def _mark_prompt_done(lang: str, cat: str, sev: str) -> None:
        with progress_lock:
            bar.update(1)
            bar.set_postfix(
                {
                    "lang": lang,
                    "cat": cat,
                    "sev": sev,
                },
                refresh=True,
            )

    def _run_item(item):
        lang, cat, sev, remaining = item
        with SessionLocal() as worker_session:
            if prompt_generation_mode == "native":
                job = GenerationJob(
                    language=lang,
                    harm_category=cat,
                    severity=sev,
                    model_id=model_id,
                    n_candidates=0,
                    run_id=run_id,
                    prompt_model_id=model_id,
                    generate_candidates=False,
                )
            else:
                job = PKUAdaptedGenerationJob(
                    language=lang,
                    harm_category=cat,
                    severity=sev,
                    model_id=model_id,
                    n_candidates=0,
                    run_id=run_id,
                    prompt_model_id=model_id,
                    source_dataset=pku_dataset,
                    generate_candidates=False,
                )
            prompt_ids = job.run(
                worker_session,
                n_prompts=remaining,
                progress_callback=lambda _prompt_id: _mark_prompt_done(lang, cat, sev),
            )
            total_cost, api_calls = (
                worker_session.query(
                    func.coalesce(func.sum(GenerationCostORM.cost_usd), 0.0),
                    func.count(GenerationCostORM.id),
                )
                .filter(GenerationCostORM.run_id == run_id)
                .one()
            )
            return lang, cat, sev, len(prompt_ids), float(total_cost), int(api_calls)

    total_remaining = sum(item[3] for item in work_items)
    bar = tqdm(
        total=total_existing + total_remaining,
        initial=total_existing,
        desc="Generating prompts",
        unit="prompt",
        dynamic_ncols=True,
    )
    try:
        with _temporary_log_levels(_QUIET_GENERATION_LOGGERS):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(_run_item, item) for item in work_items]
                for future in as_completed(futures):
                    try:
                        lang, cat, sev, count, total_cost, api_calls = future.result()
                        with progress_lock:
                            bar.set_postfix(
                                {
                                    "lang": lang,
                                    "cat": cat,
                                    "sev": sev,
                                    "cost": f"${total_cost:.2f}",
                                    "api": api_calls,
                                    "done": count,
                                },
                                refresh=True,
                            )
                    except Exception as exc:
                        with progress_lock:
                            tqdm.write(f"  [-] Prompt worker failed: {exc}")
    finally:
        bar.close()

    with SessionLocal() as session:
        now = datetime.now(tz=timezone.utc)
        monitor_run = session.get(PipelineRunORM, run_id)
        if monitor_run:
            monitor_run.current_stage = "generate_prompts"
            monitor_run.updated_at = now
        stage = (
            session.query(PipelineStageRunORM)
            .filter(
                PipelineStageRunORM.run_id == run_id,
                PipelineStageRunORM.stage_name == "generate_prompts",
            )
            .first()
        )
        if stage:
            stage.status = "completed"
            stage.completed_at = now
            stage.updated_at = now
        session.commit()

    click.secho(
        f"\n[OK] Prompt generation complete. Run ID: {run_id}\n"
        f"Next: afriguard batch-prepare-responses --run-id {run_id}",
        fg="green",
    )


# ---------------------------------------------------------------------------
# Batch response generation
# ---------------------------------------------------------------------------

@cli.command("batch-prepare-responses")
@click.option("--run-id", required=True, help="Prompt-generation run ID")
@click.option("--model", default=None, help="Response model")
@click.option("--language", "-l", default=None, help="Only prepare prompts for this language")
@click.option("--limit", default=None, type=int, help="Limit number of prompts included")
@click.option("--n-candidates", default=None, type=int, help="Candidates per prompt")
@click.option("--max-requests", default=None, type=int, help="Maximum response requests in this local batch")
@click.option("--shard-index", default=None, type=int, help="Zero-based shard index for parallel preparation")
@click.option("--shard-count", default=None, type=int, help="Total number of parallel preparation shards")
@click.option("--output-dir", default=None, type=click.Path(file_okay=False, path_type=Path))
def batch_prepare_responses(
    run_id,
    model,
    language,
    limit,
    n_candidates,
    max_requests,
    shard_index,
    shard_count,
    output_dir,
):
    """Prepare OpenAI Batch JSONL requests for response generation."""
    from src.config.generation import load_generation_config
    from src.pipeline.batch_responses import prepare_response_batch
    from src.storage.db import SessionLocal, init_db

    init_db()
    model_id = model or load_generation_config().default_model
    with SessionLocal() as session:
        try:
            job = prepare_response_batch(
                session=session,
                run_id=run_id,
                model_id=model_id,
                output_dir=output_dir,
                language=language,
                limit=limit,
                n_candidates=n_candidates,
                max_requests=max_requests,
                shard_index=shard_index,
                shard_count=shard_count,
            )
            job_id = job.id
            request_count = job.request_count
            input_file_path = job.input_file_path
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.secho("[OK] Response batch prepared.", fg="green")
    click.echo(f"  batch_job_id: {job_id}")
    click.echo(f"  requests:     {request_count}")
    click.echo(f"  input_file:   {input_file_path}")
    click.echo(f"Next: afriguard batch-submit --batch-job-id {job_id}")


@cli.command("batch-submit")
@click.option("--batch-job-id", required=True, help="Local batch job ID")
def batch_submit(batch_job_id):
    """Upload a prepared JSONL file and submit an OpenAI Batch API job."""
    from src.pipeline.batch_responses import submit_batch_job
    from src.storage.db import SessionLocal

    with SessionLocal() as session:
        job = submit_batch_job(session, batch_job_id)
        job_id = job.id
        openai_batch_id = job.openai_batch_id
        status = job.status
    click.secho("[OK] Batch submitted.", fg="green")
    click.echo(f"  batch_job_id:    {job_id}")
    click.echo(f"  openai_batch_id: {openai_batch_id}")
    click.echo(f"  status:          {status}")


@cli.command("batch-status")
@click.option("--batch-job-id", required=True, help="Local batch job ID")
def batch_status(batch_job_id):
    """Refresh and print an OpenAI Batch API job status."""
    from sqlalchemy import func
    from src.pipeline.batch_responses import refresh_batch_status
    from src.storage.db import SessionLocal, BatchRequestORM

    with SessionLocal() as session:
        job = refresh_batch_status(session, batch_job_id)
        job_id = job.id
        openai_batch_id = job.openai_batch_id
        status = job.status
        output_file_id = job.openai_output_file_id or "-"
        error_file_id = job.openai_error_file_id or "-"
        request_counts = (
            session.query(BatchRequestORM.status, func.count(BatchRequestORM.id))
            .filter(BatchRequestORM.batch_job_id == job_id)
            .group_by(BatchRequestORM.status)
            .all()
        )
    click.secho(f"Batch job: {job_id}", fg="cyan")
    click.echo(f"  openai_batch_id: {openai_batch_id}")
    click.echo(f"  status:          {status}")
    click.echo(f"  output_file_id:  {output_file_id}")
    click.echo(f"  error_file_id:   {error_file_id}")
    click.echo("  local requests:")
    for status, count in request_counts:
        click.echo(f"    {status}: {count}")


@cli.command("batch-sync")
@click.option("--batch-job-id", required=True, help="Local batch job ID")
def batch_sync(batch_job_id):
    """Download completed batch results and create candidate responses."""
    from src.pipeline.batch_responses import sync_response_batch
    from src.storage.db import SessionLocal

    with SessionLocal() as session:
        synced, failed = sync_response_batch(session, batch_job_id)
    click.secho("[OK] Batch sync complete.", fg="green")
    click.echo(f"  candidates created: {synced}")
    click.echo(f"  failed lines:        {failed}")


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------


def _print_language_id_config(language: str | None, output_format: str, audit: bool):
    import json

    import yaml

    from src.config.language_id import audit_language_id_config, load_language_id_config

    config = load_language_id_config()
    entries = list(config.languages.values())
    if language:
        language_key = language.strip().lower()
        entries = [entry for entry in entries if entry.name == language_key]
        if not entries:
            raise click.ClickException(f"No language-id config found for {language}")

    payload = {
        "path": str(config.path),
        "glotlid": {
            "enabled": config.glotlid.enabled,
            "model_path": config.glotlid.resolved_model_path,
            "top_k": config.glotlid.top_k,
            "fallback_to_legacy": config.glotlid.fallback_to_legacy,
            "fail_on_missing_model": config.glotlid.fail_on_missing_model,
        },
        "thresholds": {
            "default": config.thresholds.default,
            "short_text": config.thresholds.short_text,
            "short_text_tokens": config.thresholds.short_text_tokens,
            "contaminant_warning": config.thresholds.contaminant_warning,
            "code_switch_margin": config.thresholds.code_switch_margin,
            "related_label_multiplier": config.thresholds.related_label_multiplier,
            "mismatch_multiplier": config.thresholds.mismatch_multiplier,
        },
        "languages": [
            {
                "name": entry.name,
                "threshold": entry.threshold or config.thresholds.default,
                "short_text_threshold": entry.short_text_threshold or config.thresholds.short_text,
                "accepted_labels": sorted(entry.accepted_label_set),
                "related_labels": list(entry.related_labels),
                "contaminant_labels": list(entry.contaminant_labels),
                "review_required": entry.review_required,
                "notes": entry.notes,
            }
            for entry in entries
        ],
    }
    if audit:
        payload["audit"] = audit_language_id_config(config)

    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if output_format == "yaml":
        click.echo(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
        return

    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(f"[bold]Language ID config:[/bold] {config.path}")
    console.print(
        "GlotLID "
        f"enabled={config.glotlid.enabled} "
        f"model={config.glotlid.resolved_model_path or '(not set)'} "
        f"top_k={config.glotlid.top_k} "
        f"fallback_to_legacy={config.glotlid.fallback_to_legacy}"
    )

    table = Table(show_lines=False)
    table.add_column("Language")
    table.add_column("Threshold")
    table.add_column("Short")
    table.add_column("Accepted Labels")
    table.add_column("Related")
    table.add_column("Review")
    table.add_column("Notes")
    for entry in entries:
        table.add_row(
            entry.name,
            f"{entry.threshold or config.thresholds.default:.2f}",
            f"{entry.short_text_threshold or config.thresholds.short_text:.2f}",
            ", ".join(sorted(entry.accepted_label_set)),
            ", ".join(entry.related_labels) or "-",
            "yes" if entry.review_required else "no",
            entry.notes or "",
        )
    console.print(table)

    if audit:
        audit_result = audit_language_id_config(config)
        console.print("[bold]Audit[/bold]")
        for key, values in audit_result.items():
            console.print(f"{key}: {', '.join(values) if values else 'OK'}")


@cli.command("language-id-config")
@click.option("--language", "-l", default=None, help="Show one language only")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "yaml"]),
    default="table",
    help="Output format",
)
@click.option("--audit", is_flag=True, help="Show config coverage issues")
def language_id_config_command(language, output_format, audit):
    """Visualize editable GlotLID thresholds and label mappings."""
    _print_language_id_config(language, output_format, audit)


@cli.command("lid-config")
@click.option("--language", "-l", default=None, help="Show one language only")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "yaml"]),
    default="table",
    help="Output format",
)
@click.option("--audit", is_flag=True, help="Show config coverage issues")
def lid_config_command(language, output_format, audit):
    """Alias for language-id-config."""
    _print_language_id_config(language, output_format, audit)


@cli.command("lid-check")
@click.option("--run-id", default=None, help="Sample candidates from this run only")
@click.option("--language", "-l", default=None, help="Sample candidates for this language only")
@click.option("--status", default=None, help="Sample candidates with this status only, e.g. raw")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of candidates to test")
@click.option("--text-chars", default=120, show_default=True, type=int, help="Preview characters per row")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def lid_check(run_id, language, status, limit, text_chars, output_format):
    """Run only GlotLID on a read-only sample of database candidates."""
    import json
    from textwrap import shorten

    from rich.console import Console
    from rich.table import Table

    from src.filtering.language_detector import LanguageDetector
    from src.storage.db import CandidateResponseORM, SessionLocal

    detector = LanguageDetector(llm_router=None)
    if not detector.glotlid_available:
        raise click.ClickException(
            "GlotLID is not available. "
            f"{detector.glotlid_error or 'Set GLOTLID_MODEL_PATH to the local model.bin file.'}"
        )

    with SessionLocal() as session:
        query = session.query(CandidateResponseORM).filter(
            CandidateResponseORM.response_text.isnot(None)
        )
        if run_id:
            query = query.filter(CandidateResponseORM.run_id == run_id)
        if language:
            query = query.filter(CandidateResponseORM.language == language)
        if status:
            query = query.filter(CandidateResponseORM.status == status)

        rows = (
            query.order_by(CandidateResponseORM.created_at.desc())
            .limit(max(1, limit))
            .all()
        )

    records = []
    passed = 0
    for row in rows:
        result = detector.detect_glotlid_only(row.response_text, row.language)
        threshold = detector.glotlid_threshold_for(row.response_text, row.language)
        ok = result.confidence >= threshold
        if ok:
            passed += 1
        predictions = result.details.get("predictions", [])
        records.append(
            {
                "id": row.id,
                "run_id": row.run_id,
                "language": row.language,
                "status": row.status,
                "ok": ok,
                "detected": result.detected,
                "confidence": result.confidence,
                "threshold": threshold,
                "method": result.method,
                "top_predictions": predictions[:3],
                "error": result.details.get("error"),
                "text": row.response_text,
            }
        )

    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "count": len(records),
                    "passed": passed,
                    "failed": len(records) - passed,
                    "records": records,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    console = Console()
    if not records:
        console.print("[yellow]No matching candidates found.[/yellow]")
        return

    table = Table(show_lines=False)
    table.add_column("Language")
    table.add_column("OK")
    table.add_column("Detected")
    table.add_column("Conf")
    table.add_column("Threshold")
    table.add_column("Top Predictions")
    table.add_column("Error")
    table.add_column("Status")
    table.add_column("Text")

    for record in records:
        top_predictions = ", ".join(
            f"{label}:{prob:.2f}" for label, prob in record["top_predictions"]
        )
        preview = shorten(record["text"].replace("\n", " "), width=max(20, text_chars))
        table.add_row(
            record["language"],
            "yes" if record["ok"] else "no",
            record["detected"],
            f"{record['confidence']:.3f}",
            f"{record['threshold']:.2f}",
            top_predictions or "-",
            str(record["error"] or ""),
            record["status"],
            preview,
        )

    console.print(table)
    console.print(
        f"[bold]GlotLID-only sample:[/bold] {len(records)} candidates | "
        f"[bold]passed:[/bold] {passed} | "
        f"[bold]failed:[/bold] {len(records) - passed}"
    )


@cli.command("filter")
@click.option("--language", "-l", default=None, help="Filter candidates for this language only")
@click.option("--run-id", default=None, help="Filter only candidates from this run")
@click.option(
    "--retry-language-fail",
    is_flag=True,
    help="Re-filter candidates that previously failed language detection",
)
def filter_candidates(language, run_id, retry_language_fail):
    """Run language detection, quality scoring, similarity filtering, and deduplication."""
    from src.storage.db import SessionLocal, CandidateResponseORM, GeneratedPromptORM
    from src.filtering.language_detector import LanguageDetector
    from src.filtering.quality_scorer import QualityScorer
    from src.filtering.similarity_filter import SimilarityFilter
    from src.filtering.deduplicator import Deduplicator
    from src.generation.model_router import ModelRouter
    from src.config.filtering import load_filtering_config

    filtering_config = load_filtering_config()
    sim_threshold = filtering_config.similarity_threshold
    min_quality = filtering_config.min_quality_score

    # LLM fallback is opt-in because the normal filtering path should be local
    # and should not spend API credits.
    router = ModelRouter() if filtering_config.language_detection.llm_fallback_enabled else None
    lang_detector = LanguageDetector(llm_router=router, config=filtering_config)

    quality_scorer = QualityScorer()
    sim_filter = SimilarityFilter(threshold=sim_threshold)
    deduplicator = Deduplicator(threshold=filtering_config.deduplication_threshold)
    deduplicator.load()

    stats = {"language_fail": 0, "quality_fail": 0, "similarity_fail": 0, "dup_fail": 0, "passed": 0}

    with SessionLocal() as session:
        candidate_statuses = ["raw"]
        if retry_language_fail:
            candidate_statuses.append("filtered_language")

        query = session.query(CandidateResponseORM).filter(
            CandidateResponseORM.status.in_(candidate_statuses)
        )
        if language:
            query = query.filter(CandidateResponseORM.language == language)
        if run_id:
            query = query.filter(CandidateResponseORM.run_id == run_id)

        candidates = query.all()
        status_label = "raw + language-failed" if retry_language_fail else "raw"
        click.echo(f"[?] Filtering {len(candidates)} {status_label} candidates…")

        # Group by prompt_id for within-prompt similarity filtering
        by_prompt: dict[str, list[CandidateResponseORM]] = {}
        for c in candidates:
            by_prompt.setdefault(c.prompt_id, []).append(c)

        for prompt_id, cands in by_prompt.items():
            texts = [c.response_text for c in cands]

            # Step 1: Language detection
            lang_passed = []
            for c in cands:
                ok, det_result = lang_detector.is_acceptable(c.response_text, c.language)
                c.detected_language = det_result.detected
                c.language_score = det_result.confidence
                if not ok:
                    c.status = "filtered_language"
                    threshold = det_result.details.get("threshold")
                    threshold_text = (
                        f" threshold={threshold:.2f}" if isinstance(threshold, (int, float)) else ""
                    )
                    c.filter_reason = (
                        "Language mismatch: "
                        f"detected={det_result.detected} "
                        f"conf={det_result.confidence:.2f} "
                        f"method={det_result.method}"
                        f"{threshold_text}"
                    )[:200]
                    stats["language_fail"] += 1
                else:
                    lang_passed.append(c)

            # Step 2: Quality scoring
            quality_passed = []
            for c in lang_passed:
                score = quality_scorer.score(c.response_text, c.response_type, c.language)
                c.quality_score = score
                if score < min_quality:
                    c.status = "filtered_quality"
                    c.filter_reason = f"Low quality score: {score:.2f}"
                    stats["quality_fail"] += 1
                else:
                    quality_passed.append(c)

            # Step 3: Within-prompt similarity filtering
            if len(quality_passed) > 1:
                qp_texts = [c.response_text for c in quality_passed]
                keep_idx, max_sims = sim_filter.filter(qp_texts, language=quality_passed[0].language)
                for i, c in enumerate(quality_passed):
                    c.similarity_score = max_sims[i]
                    if i not in keep_idx:
                        c.status = "filtered_similarity"
                        c.filter_reason = f"Near-duplicate: sim={max_sims[i]:.2f}"
                        stats["similarity_fail"] += 1
                sim_passed = [quality_passed[i] for i in keep_idx]
            else:
                for c in quality_passed:
                    c.similarity_score = 0.0
                sim_passed = quality_passed

            # Step 4: Cross-batch deduplication
            for c in sim_passed:
                if deduplicator.is_duplicate(c.id, c.response_text):
                    c.status = "filtered_duplicate"
                    c.filter_reason = "Cross-batch near-duplicate"
                    stats["dup_fail"] += 1
                else:
                    c.status = "passed_filter"
                    stats["passed"] += 1

        session.commit()

    deduplicator.save()

    click.echo(f"\n[##] Filter results:")
    for k, v in stats.items():
        click.echo(f"  {k}: {v}")
    click.secho(f"\n[OK] Passed filter: {stats['passed']}", fg="green")


# ---------------------------------------------------------------------------
# assign-review
# ---------------------------------------------------------------------------

@cli.command("assign-review")
def assign_review():
    """Trigger auto-escalation of S4 items and print review queue summary."""
    from src.storage.db import SessionLocal, CandidateResponseORM
    from src.review.escalation_queue import EscalationQueue
    from sqlalchemy import func

    escalation = EscalationQueue()

    with SessionLocal() as session:
        escalated = escalation.auto_escalate_s4(session)
        click.echo(f"[!]  Auto-escalated {escalated} S4 items.")

        # Summary by language
        rows = (
            session.query(
                CandidateResponseORM.language,
                func.count(CandidateResponseORM.id)
            )
            .filter(CandidateResponseORM.status == "passed_filter")
            .group_by(CandidateResponseORM.language)
            .all()
        )

    click.echo("\n[>] Pending review tasks by language:")
    for lang, count in rows:
        click.echo(f"  {lang}: {count} candidates")

    click.secho("\n[OK] Auto-escalation done. Run 'afriguard sample-for-review' next.", fg="green")

# ---------------------------------------------------------------------------
# sample-for-review
# ---------------------------------------------------------------------------

@cli.command("sample-for-review")
@click.option("--language", "-l", default=None, help="Sample for this language only (all if not set)")
@click.option("--n-per-language", "-n", default=None, type=int, help="Maximum candidates to surface per language (default from configs/review_sampling.yaml)")
@click.option("--borderline-fraction", default=None, type=float, help="Fraction of quota from near-threshold borderline cases (default from configs/review_sampling.yaml)")
@click.option("--borderline-margin", default=None, type=float, help="Quality-score margin used to define borderline cases (default from configs/review_sampling.yaml)")
@click.option("--run-id", default=None, help="Restrict sample to this pipeline run")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility")
def sample_for_review(language, n_per_language, borderline_fraction, borderline_margin, run_id, seed):
    """
    Select a stratified sample of passed-filter candidates for human review.

    Researchers review only this sample -- not the full dataset -- to estimate
    quality, calibrate labels, and catch systematic problems. The rest of the
    dataset is exported automatically with human_reviewed=False in provenance.

    Sampling is stratified across harm category, severity, and response type
    (safe/unsafe). A configurable fraction comes from borderline cases
    (quality score near the filter threshold) to prioritise ambiguous items.
    """
    from src.storage.db import SessionLocal
    from src.review.sample_selector import SampleSelector
    from src.config.filtering import load_filtering_config
    from src.config.review_sampling import load_review_sampling_config

    sampling_config = load_review_sampling_config()
    n_per_language = (
        n_per_language
        if n_per_language is not None
        else sampling_config.n_per_language
    )
    borderline_fraction = (
        borderline_fraction
        if borderline_fraction is not None
        else sampling_config.borderline_fraction
    )
    borderline_margin = (
        borderline_margin
        if borderline_margin is not None
        else sampling_config.borderline_margin
    )
    min_quality = load_filtering_config().min_quality_score
    languages = [language] if language else None

    selector = SampleSelector()
    with SessionLocal() as session:
        result = selector.select(
            session=session,
            n_per_language=n_per_language,
            languages=languages,
            borderline_fraction=borderline_fraction,
            borderline_margin=borderline_margin,
            min_quality=min_quality,
            run_id=run_id,
            seed=seed,
        )

    d = result.to_dict()
    click.echo("\n[##] Sample-for-review summary:")
    click.echo(f"  Total eligible (passed filter): {result.total_eligible}")
    click.echo(f"  Sampled for review:             {result.sampled}")
    click.echo(f"  Review coverage:                {d['review_coverage_pct']}%")
    click.echo(f"  Borderline cases:               {result.borderline_count}")
    click.echo(f"  High-confidence cases:          {result.high_confidence_count}")
    if result.by_language:
        click.echo("\n  By language:")
        for lang, count in sorted(result.by_language.items()):
            click.echo(f"    {lang}: {count}")
    if result.by_category:
        click.echo("\n  By harm category:")
        for cat, count in sorted(result.by_category.items()):
            click.echo(f"    {cat}: {count}")
    click.secho(f"\n[OK] {result.sampled} candidates marked for review. Start review UI with: afriguard review-ui", fg="green")


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

@cli.command("assemble")
@click.option("--version", "-v", default="0.1.0", show_default=True)
@click.option("--language", "-l", default=None)
def assemble(version, language):
    """Assemble final dataset items from reviewed candidates."""
    from src.storage.db import SessionLocal
    from src.assembly.preference_builder import PreferenceBuilder
    from src.assembly.qa_builder import QABuilder
    from src.assembly.classification_builder import ClassificationBuilder

    run_id = str(uuid.uuid4())

    with SessionLocal() as session:
        pref = PreferenceBuilder().build(session, version, run_id, language)
        qa = QABuilder().build(session, version, run_id, language)
        cls_ = ClassificationBuilder().build(session, version, run_id, language)

    click.secho(
        f"\n[OK] Dataset assembled (version {version}):\n"
        f"  Preference pairs: {pref}\n"
        f"  QA items:         {qa}\n"
        f"  Classification:   {cls_}",
        fg="green"
    )


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command("export")
@click.option("--version", "-v", default="0.1.0", show_default=True)
@click.option("--language", "-l", default=None)
def export(version, language):
    """Export dataset to JSONL files with dataset card."""
    from src.storage.db import SessionLocal
    from src.assembly.dataset_versioner import DatasetVersioner

    with SessionLocal() as session:
        release_dir = DatasetVersioner().export(session, version, language)

    click.secho(f"[OK] Dataset exported to: {release_dir}", fg="green")


# ---------------------------------------------------------------------------
# run-all
# ---------------------------------------------------------------------------

@cli.command("resume-status")
@click.option("--run-id", default=None, help="Show a specific run; otherwise latest run")
def resume_status(run_id):
    """Show autoresume checkpoint status for a pipeline run."""
    from src.storage.db import SessionLocal, PipelineRunORM, PipelineStageRunORM

    with SessionLocal() as session:
        run = session.get(PipelineRunORM, run_id) if run_id else (
            session.query(PipelineRunORM)
            .order_by(PipelineRunORM.updated_at.desc())
            .first()
        )
        if run is None:
            click.secho("No pipeline run checkpoints found.", fg="yellow")
            return

        click.secho(f"Run: {run.id}", fg="cyan")
        click.echo(f"  status: {run.status}")
        click.echo(f"  current_stage: {run.current_stage or 'none'}")
        click.echo(f"  language: {run.requested_language or 'all'}")
        click.echo(f"  version: {run.dataset_version or 'n/a'}")
        click.echo(f"  n_prompts: {run.n_prompts or 'n/a'}")
        if run.error:
            click.echo(f"  error: {run.error}")

        stages = (
            session.query(PipelineStageRunORM)
            .filter(PipelineStageRunORM.run_id == run.id)
            .order_by(PipelineStageRunORM.started_at.asc())
            .all()
        )
        click.echo("\nStages:")
        for stage in stages:
            completed = stage.completed_at.isoformat() if stage.completed_at else "-"
            click.echo(
                f"  {stage.stage_name:<14} {stage.status:<10} "
                f"attempts={stage.attempts} completed={completed}"
            )
            if stage.error:
                click.echo(f"    error: {stage.error}")


@cli.command("run-all")
@click.option("--language", "-l", default=None)
@click.option("--version", "-v", default="0.1.0")
@click.option("--n-prompts", "-n", default=5)
@click.option("--model", default=None, help="Override default generation model")
@click.option(
    "--generation-mode",
    type=click.Choice(["native", "pku-adapted"]),
    default="native",
    show_default=True,
)
@click.option("--pku-max-samples", default=1000, show_default=True)
@click.option("--run-id", default=None, help="Resume or create a run with this ID")
@click.option("--resume", is_flag=True, help="Resume the latest incomplete run, or --run-id if provided")
@click.pass_context
def run_all(ctx, language, version, n_prompts, model, generation_mode, pku_max_samples, run_id, resume):
    """Run the full pipeline end-to-end (excluding human review)."""
    click.echo(f"[>>] Running full AfriGuard pipeline ({generation_mode})...\n")

    # `bootstrap-db` must always be safe to run first because it creates the
    # checkpoint tables used by autoresume.
    ctx.invoke(bootstrap_db)

    from src.storage.db import SessionLocal
    from src.pipeline.resume import PipelineResumeTracker

    with SessionLocal() as session:
        tracker = PipelineResumeTracker(session)
        run = tracker.start_or_resume_run(
            run_id=run_id,
            resume=resume,
            language=language,
            version=version,
            n_prompts=n_prompts,
        )
        active_run_id = run.id
        tracker.mark_stage_completed(active_run_id, "bootstrap_db")

    click.secho(f"[RUN] Pipeline run ID: {active_run_id}", fg="cyan")

    def invoke_resumable(stage_name, callback):
        with SessionLocal() as session:
            tracker = PipelineResumeTracker(session)
            if resume and tracker.stage_is_completed(active_run_id, stage_name):
                click.secho(f"[SKIP] {stage_name} already completed for {active_run_id}", fg="cyan")
                return
            tracker.mark_stage_started(active_run_id, stage_name)

        try:
            callback()
        except Exception as exc:
            with SessionLocal() as session:
                PipelineResumeTracker(session).mark_stage_failed(
                    active_run_id,
                    stage_name,
                    str(exc),
                )
            click.secho(
                f"\n[FAILED] Stage '{stage_name}' failed. Resume with:\n"
                f"  afriguard run-all --resume --run-id {active_run_id}",
                fg="red",
            )
            raise

        with SessionLocal() as session:
            PipelineResumeTracker(session).mark_stage_completed(active_run_id, stage_name)

    invoke_resumable(
        "ingest_seeds",
        lambda: ctx.invoke(ingest_seeds, language=language, max_samples=500, source_ids=None),
    )
    if generation_mode == "pku-adapted":
        invoke_resumable(
            "ingest_pku_prompts",
            lambda: ctx.invoke(
                ingest_pku_prompts,
                dataset="PKU-Alignment/PKU-SafeRLHF",
                split="train",
                hf_config=None,
                prompt_column="prompt",
                max_samples=pku_max_samples,
            ),
        )
    invoke_resumable(
        "generate",
        lambda: ctx.invoke(
            generate,
            language=language,
            category=None,
            severity=None,
            n_prompts=n_prompts,
            model=model,
            generation_mode=generation_mode,
            pku_dataset=None,
            run_id=active_run_id,
            progress=True,
            dry_run=False,
        ),
    )
    invoke_resumable(
        "filter",
        lambda: ctx.invoke(
            filter_candidates,
            language=language,
            run_id=active_run_id,
        ),
    )
    invoke_resumable("assign_review", lambda: ctx.invoke(assign_review))
    invoke_resumable(
        "sample_for_review",
        lambda: ctx.invoke(
            sample_for_review,
            language=language,
            n_per_language=None,
            borderline_fraction=None,
            borderline_margin=None,
            run_id=active_run_id,
            seed=42,
        ),
    )

    with SessionLocal() as session:
        PipelineResumeTracker(session).mark_run_paused(
            active_run_id,
            "Pipeline paused for human review.",
        )

    click.echo("\n[||]  Pipeline paused for human review. Run 'afriguard review-ui' to start review.")
    click.echo("   After review, run: afriguard assemble && afriguard export")
    click.echo(f"   Resume this run with: afriguard run-all --resume --run-id {active_run_id}")


# ---------------------------------------------------------------------------
# review-ui
# ---------------------------------------------------------------------------

@cli.command("monitor")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--auto-port", is_flag=True, help="Use the next available port if the requested port is busy")
def monitor(host, port, auto_port):
    """Start the pipeline progress monitor web app."""
    import uvicorn
    from src.pipeline.progress_api import app

    _host = host or os.environ.get("PIPELINE_MONITOR_HOST", "127.0.0.1")
    _port = port or int(os.environ.get("PIPELINE_MONITOR_PORT", "8010"))

    if auto_port:
        while _port < 9000 and not _port_available(_host, _port):
            _port += 1
    elif not _port_available(_host, _port):
        click.secho(
            f"[ERROR] Port {_port} is already in use on {_host}.\n"
            f"Try: afriguard monitor --port {_port + 1}\n"
            f"Or:  afriguard monitor --auto-port",
            fg="red",
        )
        raise click.Abort()

    browser_url = _browser_url(_host, _port)
    click.secho(f"[WEB] Starting pipeline monitor on {_host}:{_port}", fg="cyan")
    click.secho(f"[WEB] Open this in your browser: {browser_url}", fg="green")
    uvicorn.run(app, host=_host, port=_port)


@cli.command("review-ui")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--auto-port", is_flag=True, help="Use the next available port if the requested port is busy")
def review_ui(host, port, auto_port):
    """Start the human review web UI."""
    import uvicorn
    from src.review.annotation_interface import app

    _host = host or os.environ.get("REVIEW_UI_HOST", "127.0.0.1")
    _port = port or int(os.environ.get("REVIEW_UI_PORT", "8000"))

    if auto_port:
        while _port < 9000 and not _port_available(_host, _port):
            _port += 1
    elif not _port_available(_host, _port):
        click.secho(
            f"[ERROR] Port {_port} is already in use on {_host}.\n"
            f"Try: afriguard review-ui --port {_port + 1}\n"
            f"Or:  afriguard review-ui --auto-port",
            fg="red",
        )
        raise click.Abort()

    browser_url = _browser_url(_host, _port)
    click.secho(f"[WEB] Starting review UI on {_host}:{_port}", fg="cyan")
    click.secho(f"[WEB] Open this in your browser: {browser_url}", fg="green")
    uvicorn.run(app, host=_host, port=_port)


def _browser_url(host: str, port: int) -> str:
    """Return a browser-friendly URL for the configured bind host."""
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}"


def _port_available(host: str, port: int) -> bool:
    """Return True if the TCP host/port can be bound."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


# ---------------------------------------------------------------------------
# cost-report
# ---------------------------------------------------------------------------

@cli.command("cost-report")
def cost_report():
    """Print API cost summary."""
    from src.storage.db import SessionLocal
    from src.generation.cost_tracker import CostTracker

    with SessionLocal() as session:
        summary = CostTracker().summary(session)

    click.echo(f"\n[$] Total cost: ${summary['total_usd']:.4f} USD\n")
    click.echo(f"{'Language':<20} {'Model':<20} {'Calls':>8} {'Input Tok':>12} {'Output Tok':>12} {'Cost USD':>10}")
    click.echo("─" * 84)
    for row in summary["by_language_model"]:
        click.echo(
            f"{row['language'] or 'N/A':<20} {row['model_id']:<20} "
            f"{row['api_calls']:>8} {row['prompt_tokens']:>12} "
            f"{row['completion_tokens']:>12} ${row['total_usd']:>9.4f}"
        )


if __name__ == "__main__":
    cli()
