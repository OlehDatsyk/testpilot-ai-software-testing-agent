"""GitHub connection endpoints. Tokens never leave the backend."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project
from app.core.config import settings
from app.core.security import create_state_token, decode_state_token, encrypt_secret
from app.database.session import get_db
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    GitHubRateLimited,
    exchange_code,
    oauth_authorize_url,
    parse_repo,
)
from app.models import GitHubConnection, Project, User
from app.services.snapshots import github_token_for

router = APIRouter(prefix="/api/github", tags=["github"])


def _err(exc: GitHubError) -> HTTPException:
    if isinstance(exc, GitHubRateLimited):
        return HTTPException(429, str(exc))
    if exc.status is None:  # input validation (bad URL / branch), not an upstream failure
        return HTTPException(400, str(exc))
    return HTTPException(exc.status if exc.status in (401, 404) else 502, str(exc))


@router.get("/status")
def github_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(GitHubConnection).where(GitHubConnection.user_id == user.id))
    return {
        "oauth_configured": settings.github_oauth_configured,
        "connected": conn is not None,
        "login": conn.github_login if conn else None,
        "scopes": conn.scopes if conn else None,
        "public_access": True,
    }


@router.get("/oauth/start")
def oauth_start(include_private: bool = False, user: User = Depends(get_current_user)):
    if not settings.github_oauth_configured:
        raise HTTPException(503, "GitHub OAuth is not configured on this server (GITHUB_CLIENT_ID/SECRET/REDIRECT_URI)")
    state = create_state_token(user.id, "github-oauth")
    return {"authorize_url": oauth_authorize_url(state, include_private)}


@router.get("/oauth/callback", include_in_schema=True)
def oauth_callback(code: str = Query(max_length=200), state: str = Query(max_length=2000), db: Session = Depends(get_db)):
    """GitHub redirects the browser here. ``state`` is a signed, short-lived token bound to the user."""
    user_id = decode_state_token(state, "github-oauth")
    target = settings.frontend_url.rstrip("/") + "/settings"
    if user_id is None or db.get(User, user_id) is None:
        return RedirectResponse(target + "?github=invalid_state")
    try:
        token, scopes = exchange_code(code)
        login = GitHubClient(token).user().get("login", "unknown")
    except GitHubError:
        return RedirectResponse(target + "?github=error")
    conn = db.scalar(select(GitHubConnection).where(GitHubConnection.user_id == user_id))
    if conn is None:
        conn = GitHubConnection(user_id=user_id, github_login=login, encrypted_token=encrypt_secret(token), scopes=scopes)
        db.add(conn)
    else:
        conn.github_login, conn.encrypted_token, conn.scopes = login, encrypt_secret(token), scopes
    db.commit()
    return RedirectResponse(target + "?github=connected")


@router.delete("/connection", status_code=204)
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(GitHubConnection).where(GitHubConnection.user_id == user.id))
    if conn:
        db.delete(conn)
        db.commit()


@router.get("/repos")
def my_repos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(GitHubConnection).where(GitHubConnection.user_id == user.id))
    if conn is None:
        raise HTTPException(400, "Connect GitHub first, or import a public repository by URL")
    try:
        return GitHubClient(github_token_for(db, user.id)).user_repos()
    except GitHubError as exc:
        raise _err(exc) from exc


@router.get("/lookup")
def lookup(repository: str = Query(max_length=300), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Metadata + branches for a repository (public, or private if the connected account can see it)."""
    try:
        full = parse_repo(repository)
        client = GitHubClient(github_token_for(db, user.id))
        info = client.repo(full)
        info["branches"] = client.branches(full)
        return info
    except GitHubError as exc:
        raise _err(exc) from exc


@router.get("/projects/{project_id}/tree")
def repo_tree(ref: str | None = None, project: Project = Depends(get_project), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if not project.github_full_name:
        raise HTTPException(400, "Project is not connected to GitHub")
    try:
        client = GitHubClient(github_token_for(db, user.id))
        r = ref or project.default_branch or "main"
        return {"ref": r, "commit": client.latest_commit(project.github_full_name, r), **client.tree(project.github_full_name, r)}
    except GitHubError as exc:
        raise _err(exc) from exc
