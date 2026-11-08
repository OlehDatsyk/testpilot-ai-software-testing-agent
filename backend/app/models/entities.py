"""SQLAlchemy ORM models.

Large artefacts (repository snapshots, raw logs, generated report files) are kept
on disk under STORAGE_ROOT; the database stores metadata and paths only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Incremented on logout-all / password change to invalidate issued JWTs.
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    projects: Mapped[list[Project]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | member

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class GitHubConnection(TimestampMixin, Base):
    __tablename__ = "github_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    github_login: Mapped[str] = mapped_column(String(100))
    # Fernet-encrypted OAuth access token. Never returned by the API.
    encrypted_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(300), default="")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    repository_url: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(20), default="manual")  # manual|github|archive|demo
    github_full_name: Mapped[str | None] = mapped_column(String(200))
    default_branch: Mapped[str | None] = mapped_column(String(200))
    languages: Mapped[list] = mapped_column(JSON, default=list)
    frameworks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new|importing|analysing|ready|error
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    latest_snapshot_id: Mapped[int | None] = mapped_column(Integer)

    workspace: Mapped[Workspace] = relationship(back_populates="projects")


class RepositorySnapshot(TimestampMixin, Base):
    __tablename__ = "repository_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # github|archive|demo
    ref: Mapped[str | None] = mapped_column(String(200))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))  # relative to STORAGE_ROOT
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[list] = mapped_column(JSON, default=list)


class Job(TimestampMixin, Base):
    """Generic background job processed by the worker process."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(30), index=True)  # import|analysis|generation|execution|report
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepositoryAnalysis(TimestampMixin, Base):
    __tablename__ = "repository_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("repository_snapshots.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    tools: Mapped[dict] = mapped_column(JSON, default=dict)  # which analysers ran / were unavailable
    files_inspected: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_project_status", "project_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("repository_analyses.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(40))
    file_path: Mapped[str] = mapped_column(String(500))
    line: Mapped[int | None] = mapped_column(Integer)
    column: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(15))  # critical|high|medium|low|info
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)  # exact source line(s) read from the file
    suggestion: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(30))  # python-ast|ruff|js-rules|syntax
    certainty: Mapped[str] = mapped_column(String(15), default="potential")  # definite|potential
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|accepted|false_positive|resolved
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GeneratedTest(TimestampMixin, Base):
    __tablename__ = "generated_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("repository_snapshots.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(300))
    target_file: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(20))
    framework: Mapped[str] = mapped_column(String(20))
    expected_behaviour: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(60))  # rule-based | ai:<model>
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)  # proposed|approved|rejected
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestRun(TimestampMixin, Base):
    __tablename__ = "test_runs"
    __test__ = False  # stop pytest collecting this class
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("repository_snapshots.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(20))
    framework: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30))
    include_existing: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_test_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    log_path: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestResult(TimestampMixin, Base):
    __tablename__ = "test_results"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str | None] = mapped_column(String(500))
    classname: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(15))  # passed|failed|error|skipped
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    generated_test_id: Mapped[int | None] = mapped_column(ForeignKey("generated_tests.id", ondelete="SET NULL"))
    rule_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)


class CoverageReport(TimestampMixin, Base):
    __tablename__ = "coverage_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    line_percent: Mapped[float | None] = mapped_column(Float)
    branch_percent: Mapped[float | None] = mapped_column(Float)
    function_percent: Mapped[float | None] = mapped_column(Float)
    lines_covered: Mapped[int | None] = mapped_column(Integer)
    lines_total: Mapped[int | None] = mapped_column(Integer)
    files: Mapped[list] = mapped_column(JSON, default=list)


class BugReport(TimestampMixin, Base):
    __tablename__ = "bug_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str | None] = mapped_column(String(500))
    line: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(15), default="medium")
    category: Mapped[str] = mapped_column(String(40), default="bug")
    description: Mapped[str] = mapped_column(Text, default="")
    reproduction_steps: Mapped[str | None] = mapped_column(Text)
    expected_behaviour: Mapped[str | None] = mapped_column(Text)
    actual_behaviour: Mapped[str | None] = mapped_column(Text)
    error_output: Mapped[str | None] = mapped_column(Text)
    suggested_solution: Mapped[str | None] = mapped_column(Text)
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|in_progress|resolved|wont_fix
    source_type: Mapped[str] = mapped_column(String(20), default="manual")  # manual|finding|test_result
    source_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.id"
    )


class ConversationMessage(TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(15))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(60))  # grounded-rules | ai:<model>
    sources: Mapped[list] = mapped_column(JSON, default=list)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("test_runs.id", ondelete="SET NULL"))
    html_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(500), default="")
