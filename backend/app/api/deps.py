"""Shared API dependencies: authentication, authorisation, pagination, rate limiting."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import Project, User, WorkspaceMember

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is no longer valid", headers={"WWW-Authenticate": "Bearer"})
    return user


def workspace_ids_for(db: Session, user: User) -> list[int]:
    return list(db.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)))


def require_workspace(db: Session, user: User, workspace_id: int) -> None:
    if workspace_id not in workspace_ids_for(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")


def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
    """Load a project the caller can access. Returns 404 (not 403) to avoid leaking existence."""
    project = db.get(Project, project_id)
    if project is None or project.workspace_id not in workspace_ids_for(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


class Pagination:
    def __init__(self, page: int = Query(1, ge=1, le=100000), page_size: int = Query(25, ge=1, le=200)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class RateLimiter:
    """In-memory sliding-window limiter (per process). Adequate for a single API instance."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        if settings.environment == "test":
            return
        key = f"{request.url.path}:{request.client.host if request.client else 'unknown'}"
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; try again shortly",
                                    headers={"Retry-After": str(int(self.window))})
            q.append(now)


auth_limiter = RateLimiter(settings.auth_rate_limit_per_minute)
ai_limiter = RateLimiter(30)
