"""OpenAI Batch API support for AfriGuard response generation."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.config.generation import load_generation_config
from src.config.languages import get_language_code
from src.generation.cost_tracker import CostTracker
from src.prompt_construction.prompt_builder import PromptBuilder
from src.storage.db import (
    BatchJobORM,
    BatchRequestORM,
    CandidateResponseORM,
    GeneratedPromptORM,
)


_MODELS_PATH = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"
_DEFAULT_BATCH_DIR = Path(__file__).resolve().parents[2] / "data" / "batches"
_BATCH_COST_MULTIPLIER = 0.5


def _load_model_configs() -> dict[str, Any]:
    with open(_MODELS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("models", {})


def _is_gpt5_family(model_name: str) -> bool:
    return model_name.startswith("gpt-5")


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _safe_custom_part(value: str | None) -> str:
    return (value or "none").replace(":", "_").replace("/", "_").replace(" ", "_")


def _api_request_body(
    *,
    model_id: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    configs = _load_model_configs()
    config = configs.get(model_id)
    if config is None:
        raise ValueError(f"Unknown model_id: {model_id}. Check configs/models.yaml.")
    if config.get("provider") != "openai":
        raise ValueError("Batch response generation currently supports OpenAI models only.")

    api_model = config["model_id"]
    body: dict[str, Any] = {
        "model": api_model,
        "messages": [
            {
                "role": "developer" if _is_gpt5_family(api_model) else "system",
                "content": system_prompt,
            },
            {"role": "user", "content": user_message},
        ],
    }
    if _is_gpt5_family(api_model):
        body["max_completion_tokens"] = max_tokens
        if config.get("reasoning_effort"):
            body["reasoning_effort"] = config["reasoning_effort"]
    else:
        body.update(
            {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "frequency_penalty": config.get("frequency_penalty", 0.3),
            }
        )
    return body


def _extract_choice_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


def _usage(body: dict[str, Any]) -> tuple[int, int]:
    usage = body.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _openai_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("Install openai: pip install openai") from exc
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def _read_file_content(client, file_id: str) -> str:
    content = client.files.content(file_id)
    if hasattr(content, "read"):
        raw = content.read()
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if hasattr(content, "text"):
        return str(content.text)
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return str(content)


def prepare_response_batch(
    *,
    session: Session,
    run_id: str,
    model_id: str,
    output_dir: Path | None = None,
    language: str | None = None,
    limit: int | None = None,
    n_candidates: int | None = None,
) -> BatchJobORM:
    """Create a local response-generation JSONL file and DB batch records."""
    generation_config = load_generation_config()
    n_candidates = (
        n_candidates
        if n_candidates is not None
        else generation_config.candidates_per_prompt
    )
    n_safe, n_unsafe = generation_config.candidate_mix.response_type_counts(n_candidates)
    response_plan = [("safe", i) for i in range(n_safe)] + [
        ("unsafe", i) for i in range(n_unsafe)
    ]
    if not response_plan:
        raise ValueError("n_candidates must produce at least one response request.")

    query = (
        session.query(GeneratedPromptORM)
        .filter(
            GeneratedPromptORM.run_id == run_id,
            GeneratedPromptORM.status == "pending_response",
        )
        .order_by(GeneratedPromptORM.created_at.asc())
    )
    if language:
        query = query.filter(GeneratedPromptORM.language == language)
    if limit:
        query = query.limit(limit)
    prompts = query.all()
    if not prompts:
        raise ValueError(f"No prompts found for run_id={run_id}.")

    output_dir = output_dir or _DEFAULT_BATCH_DIR / "responses"
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_job_id = str(uuid.uuid4())
    input_path = output_dir / f"response_generation_{run_id}_{batch_job_id}.jsonl"

    builder = PromptBuilder()
    request_count = 0
    with input_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            existing = (
                session.query(BatchRequestORM.id)
                .filter(
                    BatchRequestORM.stage == "response_generation",
                    BatchRequestORM.prompt_id == prompt.id,
                )
                .first()
            )
            if existing:
                continue

            generation_params = prompt.generation_params if isinstance(prompt.generation_params, dict) else {}
            source_prompt_id = generation_params.get("source_prompt_id")

            for candidate_index, (response_type, response_offset) in enumerate(response_plan):
                system_prompt = builder.build_response_system_prompt(
                    language=prompt.language,
                    harm_category=prompt.harm_category,
                    severity=prompt.severity,
                    response_type=response_type,
                )
                body = _api_request_body(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    user_message=prompt.prompt_text,
                    temperature=generation_config.response_generation.temperature,
                    max_tokens=generation_config.response_generation.max_tokens,
                )
                custom_id = (
                    "resp:"
                    f"{_safe_custom_part(run_id)}:"
                    f"{_safe_custom_part(prompt.id)}:"
                    f"{response_type}:"
                    f"{response_offset}"
                )
                request_line = {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": body,
                }
                f.write(json.dumps(request_line, ensure_ascii=False) + "\n")
                session.add(
                    BatchRequestORM(
                        id=str(uuid.uuid4()),
                        batch_job_id=batch_job_id,
                        custom_id=custom_id,
                        stage="response_generation",
                        status="prepared",
                        language=prompt.language,
                        language_code=prompt.language_code,
                        harm_category=prompt.harm_category,
                        severity=prompt.severity,
                        prompt_id=prompt.id,
                        source_prompt_id=source_prompt_id,
                        response_type=response_type,
                        candidate_index=candidate_index,
                        model_used=model_id,
                        request_body=request_line,
                        created_at=_utcnow(),
                        updated_at=_utcnow(),
                    )
                )
                request_count += 1

    if request_count == 0:
        input_path.unlink(missing_ok=True)
        raise ValueError("No new response batch requests to prepare.")

    job = BatchJobORM(
        id=batch_job_id,
        stage="response_generation",
        status="prepared",
        endpoint="/v1/chat/completions",
        model_used=model_id,
        run_id=run_id,
        input_file_path=str(input_path),
        request_count=request_count,
        metadata_={
            "n_candidates": n_candidates,
            "safe_responses": n_safe,
            "unsafe_responses": n_unsafe,
            "language": language,
        },
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(job)
    session.commit()
    return job


def submit_batch_job(session: Session, batch_job_id: str) -> BatchJobORM:
    """Upload a prepared JSONL file and create an OpenAI batch."""
    job = session.get(BatchJobORM, batch_job_id)
    if job is None:
        raise ValueError(f"Batch job not found: {batch_job_id}")
    if job.openai_batch_id:
        return job
    if not job.input_file_path:
        raise ValueError("Batch job has no input_file_path.")

    client = _openai_client()
    input_path = Path(job.input_file_path)
    with input_path.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint=job.endpoint,
        completion_window="24h",
        metadata={"afriguard_run_id": job.run_id, "stage": job.stage},
    )

    job.openai_input_file_id = uploaded.id
    job.openai_batch_id = batch.id
    job.status = batch.status
    job.submitted_at = _utcnow()
    job.updated_at = _utcnow()
    (
        session.query(BatchRequestORM)
        .filter(BatchRequestORM.batch_job_id == job.id)
        .update({"status": "submitted", "updated_at": _utcnow()})
    )
    session.commit()
    return job


def refresh_batch_status(session: Session, batch_job_id: str) -> BatchJobORM:
    """Refresh and persist OpenAI batch status."""
    job = session.get(BatchJobORM, batch_job_id)
    if job is None:
        raise ValueError(f"Batch job not found: {batch_job_id}")
    if not job.openai_batch_id:
        raise ValueError("Batch job has not been submitted yet.")

    batch = _openai_client().batches.retrieve(job.openai_batch_id)
    job.status = batch.status
    job.openai_output_file_id = getattr(batch, "output_file_id", None)
    job.openai_error_file_id = getattr(batch, "error_file_id", None)
    job.updated_at = _utcnow()
    if batch.status == "completed":
        job.completed_at = _utcnow()
    session.commit()
    return job


def sync_response_batch(session: Session, batch_job_id: str) -> tuple[int, int]:
    """Download completed batch output and create candidate rows."""
    job = refresh_batch_status(session, batch_job_id)
    if job.status != "completed":
        raise ValueError(f"Batch job is not completed yet: {job.status}")
    if not job.openai_output_file_id:
        raise ValueError("Completed batch has no output file ID.")

    client = _openai_client()
    output_text = _read_file_content(client, job.openai_output_file_id)
    output_path = Path(job.output_file_path) if job.output_file_path else (
        Path(job.input_file_path or ".").with_suffix(".output.jsonl")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8")
    job.output_file_path = str(output_path)

    synced = 0
    failed = 0
    cost_tracker = CostTracker()
    configs = _load_model_configs()
    model_config = configs.get(job.model_used, {})

    for raw_line in output_text.splitlines():
        if not raw_line.strip():
            continue
        line = json.loads(raw_line)
        custom_id = line.get("custom_id")
        req = (
            session.query(BatchRequestORM)
            .filter(BatchRequestORM.batch_job_id == job.id, BatchRequestORM.custom_id == custom_id)
            .first()
        )
        if req is None:
            failed += 1
            continue
        if req.created_candidate_id:
            continue

        error = line.get("error")
        response = line.get("response") or {}
        status_code = int(response.get("status_code") or 0)
        body = response.get("body") or {}
        req.response_body = line
        req.updated_at = _utcnow()

        if error or status_code >= 400:
            req.status = "failed"
            req.error = json.dumps(error or body, ensure_ascii=False)
            failed += 1
            continue

        prompt = session.get(GeneratedPromptORM, req.prompt_id)
        if prompt is None:
            req.status = "failed"
            req.error = "Prompt not found during sync."
            failed += 1
            continue

        text = _extract_choice_text(body)
        prompt_tokens, completion_tokens = _usage(body)
        synchronous_cost_usd = round(
            model_config.get("cost_per_1k_input_tokens", 0.0) * prompt_tokens / 1000
            + model_config.get("cost_per_1k_output_tokens", 0.0) * completion_tokens / 1000,
            6,
        )
        cost_usd = round(synchronous_cost_usd * _BATCH_COST_MULTIPLIER, 6)
        candidate_id = str(uuid.uuid4())
        session.add(
            CandidateResponseORM(
                id=candidate_id,
                prompt_id=prompt.id,
                language=prompt.language,
                language_code=prompt.language_code or _language_code(prompt.language),
                harm_category=prompt.harm_category,
                severity=prompt.severity,
                candidate_index=req.candidate_index or 0,
                response_text=text,
                response_type=req.response_type or "unknown",
                model_used=job.model_used,
                generation_params={
                    "generation_mode": "batch_response_generation",
                    "batch_job_id": job.id,
                    "openai_batch_id": job.openai_batch_id,
                    "custom_id": custom_id,
                    "batch_cost_multiplier": _BATCH_COST_MULTIPLIER,
                    "synchronous_cost_usd": synchronous_cost_usd,
                },
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                status="raw",
                created_at=_utcnow(),
                run_id=job.run_id,
            )
        )
        cost_tracker.record(
            session=session,
            run_id=job.run_id,
            language=prompt.language,
            harm_category=prompt.harm_category,
            model_id=job.model_used,
            job_type="batch_response_gen",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        req.created_candidate_id = candidate_id
        req.status = "synced"
        prompt.status = "generated"
        synced += 1

    job.status = "synced"
    job.updated_at = _utcnow()
    session.commit()
    return synced, failed


def _language_code(language: str) -> str:
    try:
        return get_language_code(language)
    except KeyError:
        return "xx"
