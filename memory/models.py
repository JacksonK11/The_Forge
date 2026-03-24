"""
memory/models.py
Database models for The Forge — AI Build Engine.

14 tables:
  Core:        forge_runs, forge_files
  Intelligence: kb_records, meta_rules
  Knowledge:   knowledge_articles, knowledge_chunks
  Templates:   forge_templates
  Monitoring:  performance_metrics
  Updates:     forge_updates
  Registry:    agents_registry
  Costs:       build_costs
  Versioning:  build_versions
  Logs:        build_logs
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
    LargeBinary,
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
    package_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    # GitHub auto-push fields
    repo_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    push_to_github: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    github_repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    github_push_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Office callback
    callback_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Retry circuit breaker
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Full status audit trail: [{"status": "...", "timestamp": "...", "retry": n}, ...]
    status_history: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

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


# ── Update & Registry Tables ──────────────────────────────────────────────────


class ForgeUpdate(Base):
    """
    Tracks update pipeline runs — targeted codebase changes applied to an
    existing GitHub repository via clone → plan → generate → commit/push.
    """

    __tablename__ = "forge_updates"

    update_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    change_description: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    files_modified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_files_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    callback_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRegistry(Base):
    """
    Registry of all deployed agents. The Forge registers each agent it builds
    here on successful deployment. The Office reads this table for its unified
    command center view.
    """

    __tablename__ = "agents_registry"

    agent_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_url: Mapped[str] = mapped_column(String(500), nullable=False)
    dashboard_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    health_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    health_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BuildCost(Base):
    """
    Tracks exact token usage and cost (USD + AUD) for every Claude API call in the pipeline.
    One row per Claude call. Aggregated per run_id for cost dashboard.
    Alert fires via Telegram if a single build exceeds $8 AUD.
    """

    __tablename__ = "build_costs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    stage: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "parse", "architecture", "generation", "evaluation", "verification", etc.
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_aud: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BuildVersion(Base):
    """
    Semantic version tag per build run. v1.0.0 on first build, patch bumped on updates.
    Any version can be rolled back to by re-deploying the stored package_data.
    """

    __tablename__ = "build_versions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_tag: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "v1.0.0", "v1.0.1", "v1.1.0"
    version_major: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version_patch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    agent_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    github_repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BuildLog(Base):
    """
    Structured per-stage log entries for every pipeline run.
    Stored in DB so the dashboard can show an expandable per-stage log viewer.
    Weekly health report reads this for success rates and average build times.
    """

    __tablename__ = "build_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    stage: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "parse", "architecture", "generation", "package", "github_push", "deploy_verify"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(
        String(20), default="INFO", nullable=False
    )  # "INFO", "WARNING", "ERROR"
    details_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ForgeDeployFix(Base):
    """
    Tracks every deploy verification attempt and auto-fix applied by deploy_verify_fix_node.
    One row per verify/fix cycle. Accumulates the full fix history for a run.
    Stored in KB so future builds include known fixes from the start.
    """

    __tablename__ = "forge_deploy_fixes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("forge_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    update_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    health_status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "healthy", "unhealthy", "timeout"
    error_found: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fix_applied: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    files_modified: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # "health_ok", "fix_applied", "fix_failed", "no_fix_found", "max_attempts"
    endpoints_tested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    endpoints_passing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
