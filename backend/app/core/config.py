"""Application configuration loaded from environment variables.

Every setting has a safe default for local development. Production-only
requirements (e.g. a strong SECRET_KEY) are enforced in ``validate_for_runtime``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

_DEV_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # blank values in .env fall back to the defaults below
    )

    # --- Core -----------------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    secret_key: str = _DEV_SECRET
    # Optional separate key for encrypting stored GitHub tokens. Falls back to a
    # key derived from SECRET_KEY when not supplied.
    token_encryption_key: str | None = None
    access_token_expire_minutes: int = 60 * 12
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'testpilot.db').as_posix()}"
    # Create tables automatically on start-up (SQLite dev convenience only).
    # Production uses Alembic migrations.
    auto_create_tables: bool = True

    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Storage --------------------------------------------------------------
    storage_root: str = str(BACKEND_DIR / "data" / "storage")
    max_repository_size_mb: int = 50  # compressed archive limit
    max_extracted_size_mb: int = 200
    max_files_per_snapshot: int = 5000
    max_file_size_kb: int = 512  # files above this are listed but not parsed
    demo_project_path: str = str(REPO_ROOT / "demo-project")
    demo_mode_enabled: bool = True

    # --- GitHub -----------------------------------------------------------------
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None
    github_api_url: str = "https://api.github.com"
    # Optional server token used ONLY to raise rate limits for public repos.
    github_public_token: str | None = None

    # --- AI provider ----------------------------------------------------------
    ai_provider: Literal["none", "anthropic"] = "none"
    ai_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: int = 90
    ai_max_requests_per_hour: int = 60

    # --- Execution ------------------------------------------------------------
    execution_provider: Literal["disabled", "docker", "local_trusted"] = "disabled"
    execution_timeout: int = 120
    execution_memory_mb: int = 512
    execution_cpus: float = 1.0
    execution_pids_limit: int = 128
    execution_image: str = "testpilot-runner:latest"
    # local_trusted only works when this is explicitly true AND environment is
    # development. It never runs imported/uploaded code — demo project only.
    allow_local_trusted_execution: bool = False

    # --- Worker ---------------------------------------------------------------
    worker_poll_interval: float = 2.0
    # Run a job-processing thread inside the API process (single free-tier
    # service). Only permitted when EXECUTION_PROVIDER=disabled, so no
    # repository code can ever execute in the API process.
    run_worker_in_api: bool = False
    job_lease_seconds: int = 600
    job_max_attempts: int = 2

    # --- Rate limits ----------------------------------------------------------
    auth_rate_limit_per_minute: int = 20

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Render/Heroku style URLs use postgres:// — SQLAlchemy + psycopg3 need
        # postgresql+psycopg://
        if v.startswith("postgres://"):
            v = "postgresql+psycopg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret and self.github_redirect_uri)

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider != "none" and bool(self.ai_api_key)

    def validate_for_runtime(self) -> None:
        if self.environment == "production":
            if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
                raise RuntimeError("SECRET_KEY must be set to a strong value (>=32 chars) in production")
            if self.execution_provider == "local_trusted":
                raise RuntimeError("EXECUTION_PROVIDER=local_trusted is not allowed in production")
        if self.run_worker_in_api and self.execution_provider != "disabled":
            raise RuntimeError("RUN_WORKER_IN_API requires EXECUTION_PROVIDER=disabled; run `python -m app.worker` "
                               "as a separate process to use an execution provider")
        if self.environment == "production":
            if "*" in self.cors_origin_list:
                raise RuntimeError("Wildcard CORS is not allowed in production")

    def storage_path(self, *parts: str) -> Path:
        p = Path(self.storage_root).joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()


def secret_is_default() -> bool:
    return settings.secret_key == _DEV_SECRET


__all__ = ["Settings", "settings", "get_settings", "BACKEND_DIR", "REPO_ROOT", "Field"]
