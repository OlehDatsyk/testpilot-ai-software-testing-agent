"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# --- auth ------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class UserOut(ORM):
    id: int
    email: str
    name: str
    created_at: datetime


class WorkspaceOut(ORM):
    id: int
    name: str
    role: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]
    github: dict | None


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# --- projects --------------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    repository_url: str | None = Field(default=None, max_length=500)
    workspace_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class GitHubProjectIn(BaseModel):
    repository: str = Field(max_length=300, description="owner/name or https://github.com/owner/name")
    branch: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    workspace_id: int | None = None


class ReimportIn(BaseModel):
    branch: str | None = Field(default=None, max_length=200)


class ProjectOut(ORM):
    id: int
    workspace_id: int
    name: str
    description: str
    repository_url: str | None
    source_type: str
    github_full_name: str | None
    default_branch: str | None
    languages: list
    frameworks: list
    status: str
    is_demo: bool
    created_at: datetime
    updated_at: datetime
    latest_snapshot_id: int | None
    latest_analysis_at: datetime | None = None
    latest_run: dict | None = None
    open_findings: int = 0


class JobOut(ORM):
    id: int
    job_type: str
    project_id: int | None
    status: str
    error: str | None
    result: dict
    attempts: int
    max_attempts: int
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SnapshotOut(ORM):
    id: int
    source: str
    ref: str | None
    commit_sha: str | None
    file_count: int
    total_bytes: int
    skipped: list
    created_at: datetime


# --- analysis -----------------------------------------------------------------------
class AnalysisOut(ORM):
    id: int
    project_id: int
    snapshot_id: int
    summary: dict
    tools: dict
    files_inspected: int
    files_skipped: int
    duration_ms: int
    created_at: datetime


class FindingOut(ORM):
    id: int
    project_id: int
    analysis_id: int
    rule_id: str
    file_path: str
    line: int | None
    column: int | None
    severity: str
    category: str
    title: str
    description: str
    evidence: str | None
    suggestion: str | None
    method: str
    certainty: str
    status: str
    created_at: datetime
    updated_at: datetime


class FindingUpdate(BaseModel):
    status: Literal["open", "accepted", "false_positive", "resolved"]


# --- generation ------------------------------------------------------------------------
class GenerateIn(BaseModel):
    files: list[str] = Field(default_factory=list, max_length=100)
    use_ai: bool = False
    focus: str | None = Field(default=None, max_length=500)


class GeneratedTestOut(ORM):
    id: int
    project_id: int
    snapshot_id: int
    name: str
    description: str
    target: str
    target_file: str
    category: str
    language: str
    framework: str
    expected_behaviour: str
    code: str
    rationale: str
    source_files: list
    generator: str
    status: str
    validation: dict
    reviewed_at: datetime | None
    created_at: datetime


class GeneratedTestUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=50000)
    status: Literal["proposed", "approved", "rejected"] | None = None


class BulkReviewIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    status: Literal["approved", "rejected", "proposed"]


# --- runs ------------------------------------------------------------------------------
class RunIn(BaseModel):
    language: Literal["Python", "JavaScript", "TypeScript"]
    include_existing: bool = True
    generated_test_ids: list[int] = Field(default_factory=list, max_length=500)


class RunOut(ORM):
    id: int
    project_id: int
    snapshot_id: int
    job_id: int | None
    language: str
    framework: str
    provider: str
    include_existing: bool
    generated_test_ids: list
    status: str
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float | None
    exit_code: int | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    coverage: dict | None = None


class ResultOut(ORM):
    id: int
    run_id: int
    node_id: str
    name: str
    file_path: str | None
    classname: str | None
    status: str
    duration_seconds: float | None
    message: str | None
    traceback: str | None
    generated_test_id: int | None
    rule_analysis: dict | None
    ai_analysis: dict | None


class CoverageOut(ORM):
    id: int
    run_id: int
    project_id: int
    tool: str
    line_percent: float | None
    branch_percent: float | None
    function_percent: float | None
    lines_covered: int | None
    lines_total: int | None
    files: list
    created_at: datetime


# --- bugs ------------------------------------------------------------------------------
Severity = Literal["critical", "high", "medium", "low", "info"]


class BugIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    file_path: str | None = Field(default=None, max_length=500)
    line: int | None = Field(default=None, ge=1)
    severity: Severity = "medium"
    category: str = Field(default="bug", max_length=40)
    description: str = Field(default="", max_length=20000)
    reproduction_steps: str | None = Field(default=None, max_length=20000)
    expected_behaviour: str | None = Field(default=None, max_length=5000)
    actual_behaviour: str | None = Field(default=None, max_length=5000)
    error_output: str | None = Field(default=None, max_length=30000)
    suggested_solution: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=10000)


class BugUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    severity: Severity | None = None
    category: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=20000)
    reproduction_steps: str | None = Field(default=None, max_length=20000)
    expected_behaviour: str | None = Field(default=None, max_length=5000)
    actual_behaviour: str | None = Field(default=None, max_length=5000)
    suggested_solution: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=10000)
    status: Literal["open", "in_progress", "resolved", "wont_fix"] | None = None


class BugFromSourceIn(BaseModel):
    source_type: Literal["finding", "test_result"]
    source_id: int


class BugOut(ORM):
    id: int
    project_id: int
    title: str
    file_path: str | None
    line: int | None
    severity: str
    category: str
    description: str
    reproduction_steps: str | None
    expected_behaviour: str | None
    actual_behaviour: str | None
    error_output: str | None
    suggested_solution: str | None
    ai_explanation: str | None
    notes: str | None
    status: str
    source_type: str
    source_id: int | None
    created_at: datetime
    updated_at: datetime


# --- assistant / reports -----------------------------------------------------------------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


class MessageOut(ORM):
    id: int
    role: str
    content: str
    provider: str | None
    sources: list
    created_at: datetime


class ConversationOut(ORM):
    id: int
    project_id: int
    title: str
    created_at: datetime


class ReportIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    run_id: int | None = None


class ReportOut(ORM):
    id: int
    project_id: int
    title: str
    status: str
    run_id: int | None
    summary: dict
    created_at: datetime
    job_id: int | None
