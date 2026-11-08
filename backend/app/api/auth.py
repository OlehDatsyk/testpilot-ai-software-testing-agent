from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import auth_limiter, get_current_user, require_workspace
from app.core.security import (
    PASSWORD_RULES,
    create_access_token,
    hash_password,
    password_is_strong,
    verify_password,
)
from app.database.session import get_db
from app.models import GitHubConnection, User, Workspace, WorkspaceMember
from app.schemas.api import LoginIn, MeOut, RegisterIn, TokenOut, UserOut, WorkspaceIn, WorkspaceOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
ws_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Constant-time-ish behaviour for unknown emails
_DUMMY_HASH = hash_password("dummy-password-123")


@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(auth_limiter)])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not password_is_strong(body.password):
        raise HTTPException(422, f"Password must be {PASSWORD_RULES}")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    ws = Workspace(name=f"{user.name}'s workspace", owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.token_version), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id, user.token_version), user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Invalidates every token issued to this user (token version bump)."""
    user.token_version += 1
    db.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                      .where(WorkspaceMember.user_id == user.id).order_by(Workspace.id)).all()
    gh = db.scalar(select(GitHubConnection).where(GitHubConnection.user_id == user.id))
    return MeOut(user=UserOut.model_validate(user),
                 workspaces=[WorkspaceOut(id=w.id, name=w.name, role=r) for w, r in rows],
                 github={"login": gh.github_login, "scopes": gh.scopes, "connected_at": gh.created_at.isoformat()} if gh else None)


@ws_router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                      .where(WorkspaceMember.user_id == user.id).order_by(Workspace.id)).all()
    return [WorkspaceOut(id=w.id, name=w.name, role=r) for w, r in rows]


@ws_router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = Workspace(name=body.name.strip(), owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role="owner")


@ws_router.patch("/{workspace_id}", response_model=WorkspaceOut)
def rename_workspace(workspace_id: int, body: WorkspaceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_workspace(db, user, workspace_id)
    ws = db.get(Workspace, workspace_id)
    if ws.owner_id != user.id:
        raise HTTPException(403, "Only the workspace owner can rename it")
    ws.name = body.name.strip()
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role="owner")
