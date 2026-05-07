"""
AfriGuard — SQLAlchemy ORM models and database engine setup.

Uses SQLite for PoC (zero infra). Switch to PostgreSQL by changing
DATABASE_URL in .env — no code changes required.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.env import load_project_env

# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------

load_project_env()
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./afriguard.db")

_connect_args: dict[str, Any] = {}
_pool_class = None

if DATABASE_URL.startswith("sqlite"):
    # SQLite needs check_same_thread=False for multi-threaded use
    _connect_args = {"check_same_thread": False}
    _pool_class = StaticPool


def _make_engine(url: str = DATABASE_URL):
    kwargs: dict[str, Any] = {"connect_args": _connect_args}
    if _pool_class:
        kwargs["poolclass"] = _pool_class
    engine = create_engine(url, **kwargs)

    # Enable WAL mode and foreign keys for SQLite
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_session() -> Session:
    """Yield a database session (use as context manager)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class SeedDocumentORM(Base):
    __tablename__ = "seed_documents"

    id = Column(String(36), primary_key=True)
    source_id = Column(String(100), nullable=False, index=True)
    source_name = Column(String(200), nullable=False)
    source_split = Column(String(50), default="train")
    language = Column(String(50), nullable=False, index=True)
    language_code = Column(String(10), nullable=False)
    harm_domains = Column(JSON, default=list)
    text = Column(Text, nullable=False)
    original_text = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    license = Column(String(100), default="unknown")
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    provenance_hash = Column(String(64), nullable=False, unique=True, index=True)


class SourcePromptORM(Base):
    """Original prompts imported from external benchmark datasets for adaptation."""

    __tablename__ = "source_prompts"
    __table_args__ = (
        UniqueConstraint(
            "source_dataset",
            "source_split",
            "source_prompt_id",
            name="uq_source_prompt_external_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    source_dataset = Column(String(120), nullable=False, index=True)
    source_split = Column(String(50), default="train", index=True)
    source_prompt_id = Column(String(120), nullable=False, index=True)
    prompt_text = Column(Text, nullable=False)
    raw_harm_category = Column(String(120), nullable=True)
    mapped_harm_category = Column(String(10), nullable=True, index=True)
    raw_severity = Column(String(50), nullable=True)
    mapped_severity = Column(String(5), nullable=True, index=True)
    metadata_ = Column("metadata", JSON, default=dict)
    license = Column(String(100), default="unknown")
    source_url = Column(Text, nullable=True)
    provenance_hash = Column(String(64), nullable=False, unique=True, index=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class GeneratedPromptORM(Base):
    __tablename__ = "prompts"

    id = Column(String(36), primary_key=True)
    language = Column(String(50), nullable=False, index=True)
    language_code = Column(String(10), nullable=False)
    harm_category = Column(String(10), nullable=False, index=True)
    harm_category_name = Column(String(200), nullable=False)
    severity = Column(String(5), nullable=False, index=True)
    subcategory = Column(String(100), nullable=True)
    prompt_text = Column(Text, nullable=False)
    system_prompt_used = Column(Text, nullable=False)
    prompt_template_id = Column(String(100), nullable=False)
    prompt_template_version = Column(String(20), nullable=False)
    prompt_template_hash = Column(String(64), nullable=False)
    seed_document_ids = Column(JSON, default=list)
    legal_context_used = Column(Text, nullable=True)
    entities_injected = Column(JSON, default=list)
    model_used = Column(String(100), nullable=False)
    generation_params = Column(JSON, default=dict)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    status = Column(String(30), default="pending_response", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    run_id = Column(String(36), nullable=False, index=True)

    candidates = relationship("CandidateResponseORM", back_populates="prompt")


class CandidateResponseORM(Base):
    __tablename__ = "candidates"

    id = Column(String(36), primary_key=True)
    prompt_id = Column(String(36), ForeignKey("prompts.id"), nullable=False, index=True)
    language = Column(String(50), nullable=False, index=True)
    language_code = Column(String(10), nullable=False)
    harm_category = Column(String(10), nullable=False)
    severity = Column(String(5), nullable=False)
    candidate_index = Column(Integer, nullable=False)
    response_text = Column(Text, nullable=False)
    response_type = Column(String(20), nullable=False)
    detected_language = Column(String(50), nullable=True)
    language_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    similarity_score = Column(Float, nullable=True)
    status = Column(String(30), default="raw", index=True)
    filter_reason = Column(String(200), nullable=True)
    model_used = Column(String(100), nullable=False)
    generation_params = Column(JSON, default=dict)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    run_id = Column(String(36), nullable=False, index=True)

    prompt = relationship("GeneratedPromptORM", back_populates="candidates")
    annotations = relationship("AnnotationORM", back_populates="candidate")


class AnnotationORM(Base):
    __tablename__ = "annotations"

    id = Column(String(36), primary_key=True)
    candidate_id = Column(String(36), ForeignKey("candidates.id"), nullable=False, index=True)
    prompt_id = Column(String(36), ForeignKey("prompts.id"), nullable=True, index=True)
    annotator_id = Column(String(64), nullable=False, index=True)
    language = Column(String(50), nullable=False, index=True)
    decision = Column(String(20), nullable=False)
    harm_label = Column(String(20), nullable=True)
    severity_label = Column(String(5), nullable=True)
    preference_rank = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    suggested_edit = Column(Text, nullable=True)
    is_escalated = Column(Boolean, default=False)
    escalation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    candidate = relationship("CandidateResponseORM", back_populates="annotations")


class DatasetItemORM(Base):
    __tablename__ = "dataset_items"

    id = Column(String(36), primary_key=True)
    item_type = Column(String(30), nullable=False, index=True)
    language = Column(String(50), nullable=False, index=True)
    language_code = Column(String(10), nullable=False)
    harm_category = Column(String(10), nullable=False, index=True)
    harm_category_name = Column(String(200), nullable=False)
    severity = Column(String(5), nullable=False)
    prompt_id = Column(String(36), nullable=False, index=True)
    prompt_text = Column(Text, nullable=False)
    chosen_response_id = Column(String(36), nullable=True)
    chosen_response_text = Column(Text, nullable=True)
    rejected_response_id = Column(String(36), nullable=True)
    rejected_response_text = Column(Text, nullable=True)
    response_id = Column(String(36), nullable=True)
    response_text = Column(Text, nullable=True)
    classification_text = Column(Text, nullable=True)
    harm_label = Column(String(20), nullable=True)
    severity_label = Column(String(5), nullable=True)
    seed_document_ids = Column(JSON, default=list)
    prompt_template_id = Column(String(100), nullable=False)
    annotator_ids = Column(JSON, default=list)
    models_used = Column(JSON, default=list)
    dataset_version = Column(String(20), nullable=False, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class GenerationCostORM(Base):
    """Tracks API cost per job for budget management."""
    __tablename__ = "generation_costs"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), nullable=False, index=True)
    language = Column(String(50), nullable=True)
    harm_category = Column(String(10), nullable=True)
    model_id = Column(String(100), nullable=False)
    job_type = Column(String(50), nullable=False)  # 'prompt_gen', 'response_gen', 'judge'
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BatchJobORM(Base):
    """Tracks an OpenAI Batch API job created by AfriGuard."""
    __tablename__ = "batch_jobs"

    id = Column(String(36), primary_key=True)
    openai_batch_id = Column(String(120), nullable=True, unique=True, index=True)
    openai_input_file_id = Column(String(120), nullable=True)
    openai_output_file_id = Column(String(120), nullable=True)
    openai_error_file_id = Column(String(120), nullable=True)
    endpoint = Column(String(120), nullable=False, default="/v1/chat/completions")
    stage = Column(String(60), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="prepared", index=True)
    model_used = Column(String(100), nullable=False)
    run_id = Column(String(36), nullable=False, index=True)
    input_file_path = Column(Text, nullable=True)
    output_file_path = Column(Text, nullable=True)
    error_file_path = Column(Text, nullable=True)
    request_count = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    requests = relationship("BatchRequestORM", back_populates="batch_job")


class BatchRequestORM(Base):
    """Tracks one JSONL request line within a Batch API job."""
    __tablename__ = "batch_requests"
    __table_args__ = (
        UniqueConstraint("custom_id", name="uq_batch_request_custom_id"),
    )

    id = Column(String(36), primary_key=True)
    batch_job_id = Column(String(36), ForeignKey("batch_jobs.id"), nullable=False, index=True)
    custom_id = Column(String(220), nullable=False, index=True)
    stage = Column(String(60), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="prepared", index=True)
    language = Column(String(50), nullable=False, index=True)
    language_code = Column(String(10), nullable=False)
    harm_category = Column(String(10), nullable=False, index=True)
    severity = Column(String(5), nullable=False, index=True)
    prompt_id = Column(String(36), ForeignKey("prompts.id"), nullable=True, index=True)
    source_prompt_id = Column(String(120), nullable=True, index=True)
    response_type = Column(String(20), nullable=True)
    candidate_index = Column(Integer, nullable=True)
    model_used = Column(String(100), nullable=False)
    request_body = Column(JSON, default=dict)
    response_body = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_candidate_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    batch_job = relationship("BatchJobORM", back_populates="requests")


class PipelineRunORM(Base):
    """Tracks resumable end-to-end pipeline runs."""
    __tablename__ = "pipeline_runs"

    id = Column(String(36), primary_key=True)
    status = Column(String(30), nullable=False, default="running", index=True)
    current_stage = Column(String(50), nullable=True)
    requested_language = Column(String(50), nullable=True)
    dataset_version = Column(String(20), nullable=True)
    n_prompts = Column(Integer, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    stages = relationship("PipelineStageRunORM", back_populates="run")


class PipelineStageRunORM(Base):
    """Tracks one stage within a resumable pipeline run."""
    __tablename__ = "pipeline_stage_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_name", name="uq_pipeline_stage_run"),
    )

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    stage_name = Column(String(50), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSON, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    run = relationship("PipelineRunORM", back_populates="stages")


class PromptTemplateORM(Base):
    """Versioned prompt template store for provenance."""
    __tablename__ = "prompt_templates"

    id = Column(String(100), primary_key=True)   # e.g. 'H01_hate_speech_v1'
    version = Column(String(20), nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True)
    harm_category = Column(String(10), nullable=False, index=True)
    template_content = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    Base.metadata.create_all(bind=engine)
