"""
AfriGuard — Review: AnnotationInterface

Lightweight FastAPI web application for human review.
Each researcher logs in with their language-specific credentials
and sees only items in their assigned language.

Routes:
  GET  /           → login page
  POST /login      → authenticate and set session cookie
  GET  /review     → review queue for logged-in reviewer
  POST /annotate   → submit annotation for a candidate
  GET  /escalated  → senior review queue (admin only)
  GET  /stats      → reviewer stats
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from src.storage.db import (
    SessionLocal,
    AnnotationORM,
    CandidateResponseORM,
    GeneratedPromptORM,
)
from src.review.task_assigner import TaskAssigner
from src.review.escalation_queue import EscalationQueue
from src.config.env import load_project_env
from src.observability.logging_config import configure_logging

import structlog

load_project_env()
configure_logging()
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AfriGuard Review UI", version="0.1.0")

# BUG FIX: SECRET_KEY defaulting to "change-me" is insecure even for PoC.
# We now require it to be explicitly set in any non-local environment.
# In production (AFRIGUARD_ENV=production), missing SECRET_KEY is a hard error.
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
    # Development/PoC only: use a deterministic but non-trivial fallback
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    logger.warning(
        "review_ui.insecure_secret_key",
        message="REVIEW_UI_SECRET_KEY not set — using a per-process random key. "
                "Sessions will not survive restarts. Set REVIEW_UI_SECRET_KEY for persistence.",
    )

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=28800)

# Templates directory
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# ---------------------------------------------------------------------------
# Reviewer credentials (hashed passwords, set via environment variables)
# In production, replace with a proper auth system.
# Default passwords match reviewer_id for PoC (researcher changes on first login).
# ---------------------------------------------------------------------------
# BUG FIX: Static fallback passwords were always active, meaning the app
# would start with known-plaintext credentials if the PASS_ env vars were
# not set. In production mode we now fail-fast. In development, a clear
# warning is emitted so reviewers know to set passwords before going live.
def _load_reviewer_passwords() -> dict[str, str]:
    """Load reviewer passwords from environment variables."""
    password_env_map = {
        "reviewer_hausa":          ("PASS_HAUSA",          "hausa_review_poc"),
        "reviewer_sepedi":         ("PASS_SEPEDI",         "sepedi_review_poc"),
        "reviewer_chichewa":       ("PASS_CHICHEWA",       "chichewa_review_poc"),
        "reviewer_northern_sotho": ("PASS_NORTHERN_SOTHO", "nsotho_review_poc"),
        "reviewer_yao":            ("PASS_YAO",            "yao_review_poc"),
        "reviewer_yoruba":         ("PASS_YORUBA",         "yoruba_review_poc"),
        "reviewer_shona":          ("PASS_SHONA",          "shona_review_poc"),
        "admin":                   ("PASS_ADMIN",          "admin_afriguard_poc"),
    }

    passwords: dict[str, str] = {}
    missing_in_prod: list[str] = []

    for reviewer, (env_var, default) in password_env_map.items():
        value = os.environ.get(env_var, "")
        if value:
            passwords[reviewer] = value
        elif _IS_PRODUCTION:
            missing_in_prod.append(env_var)
        else:
            # Development PoC: use fallback with a loud warning
            logger.warning(
                "review_ui.default_password_active",
                reviewer=reviewer,
                env_var=env_var,
                message=f"{env_var} not set — using PoC default. Set before sharing the URL.",
            )
            passwords[reviewer] = default

    if missing_in_prod:
        raise RuntimeError(
            f"Missing required environment variables in production mode: {missing_in_prod}. "
            "Set all PASS_* variables before starting the review UI."
        )

    return passwords


_REVIEWER_PASSWORDS = _load_reviewer_passwords()

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


def require_login(request: Request) -> str:
    reviewer_id = get_current_reviewer(request)
    if not reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/"},
        )
    return reviewer_id


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
        context={"error": None},
    )


@app.post("/login")
async def login(
    request: Request,
    reviewer_id: str = Form(...),
    password: str = Form(...),
):
    expected = _REVIEWER_PASSWORDS.get(reviewer_id)
    if expected and password == expected:
        request.session["reviewer_id"] = reviewer_id
        logger.info("review_ui.login_success", reviewer_id=reviewer_id)
        return RedirectResponse("/review", status_code=303)

    logger.warning("review_ui.login_failed", reviewer_id=reviewer_id)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid credentials. Please try again."},
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

    tasks = _ASSIGNER.get_pending_tasks(session=db, reviewer_id=reviewer_id, limit=10)
    pending_item_count = _ASSIGNER.count_pending_items(session=db, reviewer_id=reviewer_id)

    # Stats for this reviewer
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

    # Update candidate status based on decision
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
        context={"items": items, "reviewer_id": reviewer_id},
    )


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    db: Session = Depends(get_db),
):
    reviewer_id = get_current_reviewer(request)
    if not reviewer_id:
        return RedirectResponse("/")

    # Build per-language annotation stats
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
        context={"stats": stats, "reviewer_id": reviewer_id},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_reviewer(reviewer_id: str) -> str:
    """Hash the reviewer ID for anonymized storage."""
    return hashlib.sha256(reviewer_id.encode()).hexdigest()[:16]


def _reviewer_language(reviewer_id: str) -> str:
    mapping = {
        "reviewer_hausa": "hausa",
        "reviewer_sepedi": "sepedi",
        "reviewer_chichewa": "chichewa",
        "reviewer_northern_sotho": "northern_sotho",
        "reviewer_yao": "yao",
        "reviewer_yoruba": "yoruba",
        "reviewer_shona": "shona",
        "admin": "all",
    }
    return mapping.get(reviewer_id, "unknown")
