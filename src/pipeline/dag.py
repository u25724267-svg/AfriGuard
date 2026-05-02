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

import os
import uuid
from pathlib import Path

import click
import structlog

from src.config.env import load_project_env
from src.observability.logging_config import configure_logging

load_project_env()
configure_logging()
logger = structlog.get_logger(__name__)

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
# generate
# ---------------------------------------------------------------------------

@cli.command("generate")
@click.option("--language", "-l", default=None, help="Target language (all if not set)")
@click.option("--category", "-c", default=None, help="Harm category ID (e.g. H01)")
@click.option("--severity", "-s", default=None, help="Severity code (S1-S4)")
@click.option("--n-prompts", "-n", default=5, show_default=True, help="Prompts per combination")
@click.option("--model", default=None, help="Override default model (e.g. gpt-4o)")
@click.option("--run-id", default=None, help="Reuse an existing pipeline run ID")
@click.option("--dry-run", is_flag=True, help="Print config without calling API")
def generate(language, category, severity, n_prompts, model, run_id, dry_run):
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
        f"   Model: {model_id}"
    )

    if dry_run:
        click.secho("[?] Dry run — no API calls made.", fg="yellow")
        for lang in languages:
            for cat in categories:
                for sev in severities:
                    click.echo(f"  Would generate: {lang} / {cat} / {sev}")
        return

    from src.storage.db import SessionLocal, GeneratedPromptORM
    from src.generation.generation_job import GenerationJob

    run_id = run_id or str(uuid.uuid4())
    click.echo(f"   Run ID: {run_id}\n")

    with SessionLocal() as session:
        for lang in languages:
            for cat in categories:
                for sev in severities:
                    existing = (
                        session.query(GeneratedPromptORM)
                        .filter(
                            GeneratedPromptORM.run_id == run_id,
                            GeneratedPromptORM.language == lang,
                            GeneratedPromptORM.harm_category == cat,
                            GeneratedPromptORM.severity == sev,
                            GeneratedPromptORM.status == "generated",
                        )
                        .count()
                    )
                    remaining = max(0, n_prompts - existing)
                    if remaining == 0:
                        click.secho(
                            f"  Skipping {lang} / {cat} / {sev}: {existing}/{n_prompts} prompts already generated",
                            fg="cyan",
                        )
                        continue

                    click.echo(
                        f"  Generating {lang} / {cat} / {sev} "
                        f"({remaining} remaining, {existing} existing)…",
                        nl=False,
                    )
                    try:
                        job = GenerationJob(
                            language=lang,
                            harm_category=cat,
                            severity=sev,
                            model_id=model_id,
                            n_candidates=n_candidates,
                            run_id=run_id,
                        )
                        prompt_ids = job.run(session=session, n_prompts=remaining)
                        click.secho(f" [+] {len(prompt_ids)} prompts", fg="green")
                    except Exception as e:
                        click.secho(f" [-] {e}", fg="red")

    click.secho(f"\n[OK] Generation complete. Run ID: {run_id}", fg="green")


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------

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

    # BUG FIX: LanguageDetector was constructed without a router, so the
    # LLM fallback tier for low-resource languages (Yao, Sepedi, Northern
    # Sotho) was silently disabled. We now pass a ModelRouter so the
    # three-tier cascade (langdetect → langid → LLM) actually fires.
    router = ModelRouter()
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
                    c.filter_reason = f"Language mismatch: detected={det_result.detected} conf={det_result.confidence:.2f}"
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
@click.option("--run-id", default=None, help="Resume or create a run with this ID")
@click.option("--resume", is_flag=True, help="Resume the latest incomplete run, or --run-id if provided")
@click.pass_context
def run_all(ctx, language, version, n_prompts, run_id, resume):
    """Run the full pipeline end-to-end (excluding human review)."""
    click.echo("[>>] Running full AfriGuard pipeline...\n")

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
    invoke_resumable(
        "generate",
        lambda: ctx.invoke(
            generate,
            language=language,
            category=None,
            severity=None,
            n_prompts=n_prompts,
            model=None,
            run_id=active_run_id,
            dry_run=False,
        ),
    )
    invoke_resumable(
        "filter",
        lambda: ctx.invoke(
            filter_candidates,
            language=language,
            run_id=active_run_id,
            retry_language_fail=False,
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

    browser_url = _review_ui_browser_url(_host, _port)
    click.secho(f"[WEB] Starting review UI on {_host}:{_port}", fg="cyan")
    click.secho(f"[WEB] Open this in your browser: {browser_url}", fg="green")
    uvicorn.run(app, host=_host, port=_port)


def _review_ui_browser_url(host: str, port: int) -> str:
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
