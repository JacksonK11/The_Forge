"""
memory/models.py
Database models for The Forge — AI Build Engine.

8 tables:
  Core:        forge_runs, forge_files
  Intelligence: kb_records, meta_rules
  Knowledge:   knowledge_articles, knowledge_chunks
  Templates:   forge_templates
  Monitoring:  performance_metrics
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────


class RunStatus(str, Enum):
    QUEUED = "queued"
    VALIDATING = "validating"
    PARSING = "parsing"
    CONFIRMING = "confirming"
    ARCHITECTING = "architecting"
    GENERATING = "generating"
    PACKAGING = "packaging"
    COMPLETE = "complete"
    FAILED = "failed"


class FileStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    RETRYING = "retrying"


# ── Core Tables ──────────────────────────────────────────────────────────────


class ForgeRun(Base):
    """One row per blueprint build. Central tracking record for a pipeline run."""

    __tablename__ = "forge_runs"

    run_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    blueprint_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blueprint_file_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=RunStatus.QUEUED.value, nullable=False
    )
    spec_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    manifest_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_complete: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    package_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    files: Mapped[list["ForgeFile"]] = relationship(
        "ForgeFile", back_populates="run", cascade="all, delete-orphan"
    )
    kb_records: Mapped[list["KbRecord"]] = relationship(
        "KbRecord", back_populates="run"
    )


class ForgeFile(Base):
    """One row per generated file within a run."""

    __tablename__ = "forge_files"

    file_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    layer: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=FileStatus.PENDING.value, nullable=False
    )
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["ForgeRun"] = relationship("ForgeRun", back_populates="files")


# ── Intelligence Tables ───────────────────────────────────────────────────────


class KbRecord(Base):
    """
    Knowledge base outcome records.
    Stores successful/failed build patterns with embeddings for similarity retrieval.
    Agent improves with every build by retrieving similar past patterns.
    """

    __tablename__ = "kb_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    record_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "build_pattern", "deployment_failure", "file_pattern", "architecture_decision"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # "success", "failure"
    embedding = mapped_column(Vector(1536), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Optional["ForgeRun"]] = relationship(
        "ForgeRun", back_populates="kb_records"
    )


class MetaRule(Base):
    """
    Auto-extracted operational rules from real build outcomes.
    Weekly job analyses outcomes and updates these — agent self-improves without code changes.
    """

    __tablename__ = "meta_rules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    rule_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "generation", "architecture", "deployment", "validation"
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    applied_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Knowledge Engine Tables ───────────────────────────────────────────────────


class KnowledgeArticle(Base):
    """
    Collected articles from web search, RSS feeds, and YouTube.
    Content hash prevents duplicate ingestion.
    """

    __tablename__ = "knowledge_articles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    domain: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "fastapi", "sqlalchemy", "fly_io", "rq", "react_vite"
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "web", "rss", "youtube"
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="article", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    """
    400-token overlapping chunks of knowledge articles with OpenAI embeddings.
    Retrieved via pgvector similarity before every major Claude call.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    article_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    article: Mapped["KnowledgeArticle"] = relationship(
        "KnowledgeArticle", back_populates="chunks"
    )


# ── Template & Monitoring Tables ─────────────────────────────────────────────


class ForgeTemplate(Base):
    """Starter blueprint templates for common agent types."""

    __tablename__ = "forge_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "research_agent", "trading_bot", "customer_service", "data_pipeline", "monitoring_agent"
    description: Mapped[str] = mapped_column(Text, nullable=False)
    blueprint_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PerformanceMetric(Base):
    """KPI snapshots recorded every 6 hours by the performance monitor."""

    __tablename__ = "performance_metrics"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    metric_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "builds_completed", "avg_build_time_seconds", "success_rate", "avg_files_per_build", "api_cost_usd"
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    details_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
