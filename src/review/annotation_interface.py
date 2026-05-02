"""
AfriGuard - Review: AnnotationInterface

Lightweight FastAPI web application for human review.
Researchers select the language they want to review and are signed in
automatically. The admin account remains password-protected for escalations.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.config.env import load_project_env
from src.config.languages import get_reviewer_accounts, get_reviewer_language
from src.config.review_ui import load_review_ui_config
from src.observability.logging_config import configure_logging
from src.review.escalation_queue import EscalationQueue
from src.review.task_assigner import TaskAssigner
from src.storage.db import (
    AnnotationORM,
    CandidateResponseORM,
    SessionLocal,
)

load_project_env()
configure_logging()
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AfriGuard Review UI", version="0.1.0")

_IS_PRODUCTION = os.environ.get("AFRIGUARD_ENV", "development").lower() == "production"
SECRET_KEY = os.environ.get("REVIEW_UI_SECRET_KEY", "")
_PLACEHOLDER_SECRET_KEYS = {
    "change-me",
    "change-me-to-a-random-secret-in-production",
}

if not SECRET_KEY or SECRET_KEY in _PLACEHOLDER_SECRET_KEYS:
    if _IS_PRODUCTION:
        raise RuntimeError(
            "REVIEW_UI_SECRET_KEY environment variable is not set to a secure value. "
            "This is required in production. Set it to a random 32+ character string."
        )
    import secrets as _secrets

    SECRET_KEY = _secrets.token_hex(32)
    logger.warning(
        "review_ui.insecure_secret_key",
        message=(
            "REVIEW_UI_SECRET_KEY not set - using a per-process random key. "
            "Sessions will not survive restarts. Set REVIEW_UI_SECRET_KEY for persistence."
        ),
    )

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=28800)

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# ---------------------------------------------------------------------------
# Reviewer access
# ---------------------------------------------------------------------------

_REVIEWER_OPTIONS = get_reviewer_accounts()
_REVIEWER_IDS = {account["reviewer_id"] for account in _REVIEWER_OPTIONS}
_UI_CONFIG = load_review_ui_config()


def _load_admin_password() -> str:
    """Load the admin password from PASS_ADMIN."""
    value = os.environ.get("PASS_ADMIN", "")
    if value:
        return value
    if _IS_PRODUCTION:
        raise RuntimeError("PASS_ADMIN is required when AFRIGUARD_ENV=production.")

    logger.warning(
        "review_ui.default_admin_password_active",
        env_var="PASS_ADMIN",
        message="PASS_ADMIN not set - using PoC default. Set before sharing the URL.",
    )
    return "admin_afriguard_poc"


_ADMIN_PASSWORD = _load_admin_password()

_ASSIGNER = TaskAssigner()
_ESCALATION = EscalationQueue()


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def get_current_reviewer(request: Request) -> str | None:
    return request.session.get("reviewer_id")


def _hash_reviewer(reviewer_id: str) -> str:
    """Hash the reviewer ID for anonymized storage."""
    return hashlib.sha256(reviewer_id.encode()).hexdigest()[:16]


def _reviewer_language(reviewer_id: str) -> str:
    if reviewer_id == "admin":
        return "all"
    return get_reviewer_language(reviewer_id) or "unknown"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    reviewer_id = get_current_reviewer(request)
    if reviewer_id:
        return RedirectResponse("/review")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "reviewer_options": _REVIEWER_OPTIONS,
            "ui": _UI_CONFIG.template_context(),
        },
    )


@app.post("/login")
async def login(
    request: Request,
    reviewer_id: str = Form(...),
    password: str = Form(default=""),
):
    if reviewer_id in _REVIEWER_IDS:
        request.session["reviewer_id"] = reviewer_id
        logger.info("review_ui.reviewer_login_success", reviewer_id=reviewer_id)
        return RedirectResponse("/review", status_code=303)

    if reviewer_id == "admin" and password == _ADMIN_PASSWORD:
        request.session["reviewer_id"] = reviewer_id
        logger.info("review_ui.admin_login_success")
        return RedirectResponse("/review", status_code=303)

    logger.warning("review_ui.login_failed", reviewer_id=reviewer_id)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": _UI_CONFIG.text.invalid_login_error,
            "reviewer_options": _REVIEWER_OPTIONS,
            "ui": _UI_CONFIG.template_context(),
        },
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/review", response_class=HTMLResponse)
async def review_queue(
    request: Request,
    db: Session = Depends(get_db),
):
    reviewer_id = get_current_reviewer(request)
    if not reviewer_id:
        return RedirectResponse("/")

    tasks = _ASSIGNER.get_pending_tasks(
        session=db,
        reviewer_id=reviewer_id,
        limit=_UI_CONFIG.tasks_per_page,
    )
    pending_item_count = _ASSIGNER.count_pending_items(session=db, reviewer_id=reviewer_id)

    annotated_count = (
        db.query(AnnotationORM)
        .filter(AnnotationORM.annotator_id == _hash_reviewer(reviewer_id))
        .count()
    )

    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "reviewer_id": reviewer_id,
            "tasks": [
                {
                    "prompt_id": t.prompt_id,
                    "prompt_text": t.prompt_text,
                    "language": t.language,
                    "harm_category": t.harm_category,
                    "severity": t.severity,
                    "candidates": t.candidates,
                }
                for t in tasks
            ],
            "annotated_count": annotated_count,
            "pending_count": pending_item_count,
            "task_group_count": len(tasks),
            "ui": _UI_CONFIG.template_context(),
        },
    )


@app.post("/annotate")
async def submit_annotation(
    request: Request,
    prompt_id: str = Form(...),
    candidate_id: str = Form(...),
    decision: str = Form(...),
    harm_label: str = Form(default=""),
    severity_label: str = Form(default=""),
    preference_rank: str = Form(default=""),
    notes: str = Form(default=""),
    suggested_edit: str = Form(default=""),
    escalate: str = Form(default=""),
    db: Session = Depends(get_db),
):
    reviewer_id = get_current_reviewer(request)
    if not reviewer_id:
        return RedirectResponse("/")

    is_escalated = escalate.lower() in ("true", "1", "yes", "on")
    escalation_reason = "Annotator requested escalation" if is_escalated else None

    ann = AnnotationORM(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        prompt_id=prompt_id,
        annotator_id=_hash_reviewer(reviewer_id),
        language=_reviewer_language(reviewer_id),
        decision=decision,
        harm_label=harm_label or None,
        severity_label=severity_label or None,
        preference_rank=int(preference_rank) if preference_rank.isdigit() else None,
        notes=notes or None,
        suggested_edit=suggested_edit or None,
        is_escalated=is_escalated,
        escalation_reason=escalation_reason,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(ann)

    candidate = db.get(CandidateResponseORM, candidate_id)
    if candidate:
        if decision == "approve":
            candidate.status = "approved"
        elif decision == "reject":
            candidate.status = "rejected"
        elif decision in ("flag", "escalate"):
            candidate.status = "flagged"

    db.commit()

    logger.info(
        "review_ui.annotation_submitted",
        reviewer_id=reviewer_id,
        candidate_id=candidate_id,
        decision=decision,
        escalated=is_escalated,
    )
    return RedirectResponse("/review", status_code=303)


@app.get("/escalated", response_class=HTMLResponse)
async def escalated_queue(
    request: Request,
    db: Session = Depends(get_db),
):
    reviewer_id = get_current_reviewer(request)
    if reviewer_id != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    items = _ESCALATION.get_escalated_annotations(db)
    return templates.TemplateResponse(
        request=request,
        name="escalated.html",
        context={
            "items": items,
            "reviewer_id": reviewer_id,
            "ui": _UI_CONFIG.template_context(),
        },
    )


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    db: Session = Depends(get_db),
):
    reviewer_id = get_current_reviewer(request)
    if not reviewer_id:
        return RedirectResponse("/")

    from sqlalchemy import func

    rows = (
        db.query(
            AnnotationORM.language,
            AnnotationORM.decision,
            func.count(AnnotationORM.id).label("count"),
        )
        .group_by(AnnotationORM.language, AnnotationORM.decision)
        .all()
    )

    stats: dict[str, dict[str, int]] = {}
    for lang, decision, count in rows:
        if lang not in stats:
            stats[lang] = {}
        stats[lang][decision] = count

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "stats": stats,
            "reviewer_id": reviewer_id,
            "ui": _UI_CONFIG.template_context(),
        },
    )
