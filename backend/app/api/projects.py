from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, get_project, require_workspace, workspace_ids_for
from app.core.config import settings
from app.database.session import get_db
from app.integrations.github import GitHubClient, GitHubError, parse_repo, validate_branch
from app.models import Finding, Job, Project, RepositoryAnalysis, RepositorySnapshot, TestRun, User
from app.schemas.api import (
    GitHubProjectIn,
    JobOut,
    Page,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
    ReimportIn,
    SnapshotOut,
)
from app.services.jobs import ACTIVE, enqueue, log_activity
from app.services.snapshots import github_token_for, snapshot_root

router = APIRouter(prefix="/api/projects", tags=["projects"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _default_workspace(db: Session, user: User, workspace_id: int | None) -> int:
    ids = workspace_ids_for(db, user)
    if not ids:
        raise HTTPException(400, "User has no workspace")
    if workspace_id is None:
        return ids[0]
    require_workspace(db, user, workspace_id)
    return workspace_id


def project_out(db: Session, p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    a = db.scalars(select(RepositoryAnalysis).where(RepositoryAnalysis.project_id == p.id)
                   .order_by(RepositoryAnalysis.id.desc()).limit(1)).first()
    if a:
        out.latest_analysis_at = a.created_at
        out.open_findings = db.scalar(select(func.count()).select_from(Finding)
                                      .where(Finding.analysis_id == a.id, Finding.status == "open")) or 0
    r = db.scalars(select(TestRun).where(TestRun.project_id == p.id).order_by(TestRun.id.desc()).limit(1)).first()
    if r:
        out.latest_run = {"id": r.id, "status": r.status, "passed": r.passed, "failed": r.failed, "total": r.total,
                          "created_at": r.created_at.isoformat()}
    return out


@router.get("", response_model=Page[ProjectOut])
def list_projects(q: str | None = Query(None, max_length=100), status: str | None = Query(None, max_length=20),
                  language: str | None = Query(None, max_length=30), pg: Pagination = Depends(),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Project).where(Project.workspace_id.in_(workspace_ids_for(db, user)))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Project.name).like(like), func.lower(Project.description).like(like),
                              func.lower(func.coalesce(Project.github_full_name, "")).like(like)))
    if status:
        stmt = stmt.where(Project.status == status)
    projects = db.scalars(stmt.order_by(Project.updated_at.desc())).all()
    if language:
        projects = [p for p in projects if language in (p.languages or [])]
    total = len(projects)
    items = [project_out(db, p) for p in projects[pg.offset: pg.offset + pg.page_size]]
    return Page(items=items, total=total, page=pg.page, page_size=pg.page_size)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _default_workspace(db, user, body.workspace_id)
    p = Project(workspace_id=ws, created_by=user.id, name=body.name.strip(), description=body.description,
                repository_url=body.repository_url, source_type="manual", languages=[], frameworks=[])
    db.add(p)
    db.flush()
    log_activity(db, p, user.id, "project.created", p.name)
    db.commit()
    return project_out(db, p)


@router.post("/github", response_model=ProjectOut, status_code=201)
def create_from_github(body: GitHubProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        full = parse_repo(body.repository)
        info = GitHubClient(github_token_for(db, user.id)).repo(full)
        branch = validate_branch(body.branch or info["default_branch"] or "main")
    except GitHubError as exc:
        raise HTTPException(exc.status if exc.status in (401, 404, 429) else 400, str(exc)) from exc
    ws = _default_workspace(db, user, body.workspace_id)
    p = Project(workspace_id=ws, created_by=user.id, name=(body.name or info["full_name"]).strip()[:120],
                description=info["description"][:2000], repository_url=info["html_url"], source_type="github",
                github_full_name=info["full_name"], default_branch=branch, languages=[], frameworks=[], status="importing")
    db.add(p)
    db.flush()
    enqueue(db, "import", project_id=p.id, owner_id=user.id, payload={"source": "github", "ref": branch})
    log_activity(db, p, user.id, "project.created", f"GitHub {info['full_name']} @ {branch}")
    db.commit()
    return project_out(db, p)


@router.post("/upload", response_model=ProjectOut, status_code=201)
async def create_from_archive(name: str = Form(..., min_length=1, max_length=120), description: str = Form("", max_length=2000),
                              archive: UploadFile = File(...), user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    fname = (archive.filename or "").lower()
    if not fname.endswith((".zip", ".tar.gz", ".tgz")):
        raise HTTPException(415, "Upload a .zip or .tar.gz archive")
    limit = settings.max_repository_size_mb * 1024 * 1024
    data = bytearray()
    while chunk := await archive.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"Archive exceeds {settings.max_repository_size_mb} MB")
    uploads = settings.storage_path("uploads")
    path = uploads / f"{uuid.uuid4().hex}.bin"
    path.write_bytes(bytes(data))
    ws = _default_workspace(db, user, None)
    p = Project(workspace_id=ws, created_by=user.id, name=name.strip(), description=description, source_type="archive",
                languages=[], frameworks=[], status="importing")
    db.add(p)
    db.flush()
    enqueue(db, "import", project_id=p.id, owner_id=user.id, payload={"source": "archive", "upload_path": str(path)})
    log_activity(db, p, user.id, "project.created", f"Archive upload {archive.filename}"[:200])
    db.commit()
    return project_out(db, p)


@router.post("/demo", response_model=ProjectOut, status_code=201)
def create_demo(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not settings.demo_mode_enabled:
        raise HTTPException(403, "Demo mode is disabled on this server")
    if not Path(settings.demo_project_path).is_dir():
        raise HTTPException(503, "Demo project files are not available on this server")
    ws = _default_workspace(db, user, None)
    p = Project(workspace_id=ws, created_by=user.id, name="Demo · Corner Shop Inventory",
                description="DEMO PROJECT — written for TestPilot with deliberate defects. Not a real customer repository.",
                source_type="demo", is_demo=True, languages=[], frameworks=[], status="importing")
    db.add(p)
    db.flush()
    enqueue(db, "import", project_id=p.id, owner_id=user.id, payload={"source": "demo"})
    log_activity(db, p, user.id, "project.created", "Demo project")
    db.commit()
    return project_out(db, p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return project_out(db, project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update(body: ProjectUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    if body.name is not None:
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description
    db.commit()
    return project_out(db, project)


@router.delete("/{project_id}", status_code=204)
def delete(project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(Job).where(Job.project_id == project.id, Job.status.in_(ACTIVE))):
        raise HTTPException(409, "Project has running jobs; cancel them or wait before deleting")
    pid = project.id
    log_activity(db, None, user.id, "project.deleted", project.name, workspace_id=project.workspace_id)
    db.delete(project)
    db.commit()
    for sub in ("snapshots", "reports"):
        shutil.rmtree(Path(settings.storage_root) / sub / str(pid), ignore_errors=True)


@router.post("/{project_id}/import", response_model=JobOut, status_code=202)
def reimport(body: ReimportIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    if project.source_type == "github":
        try:
            ref = validate_branch(body.branch or project.default_branch or "main")
        except GitHubError as exc:
            raise HTTPException(400, str(exc)) from exc
        project.default_branch = ref
        payload = {"source": "github", "ref": ref}
    elif project.source_type == "demo":
        payload = {"source": "demo"}
    else:
        raise HTTPException(400, "Re-import is available for GitHub and demo projects; upload a new archive instead")
    project.status = "importing"
    job = enqueue(db, "import", project_id=project.id, owner_id=user.id, payload=payload)
    db.commit()
    return job


@router.post("/{project_id}/analyse", response_model=JobOut, status_code=202)
def analyse(project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not project.latest_snapshot_id:
        raise HTTPException(400, "Import the project's code before analysing it")
    project.status = "analysing"
    job = enqueue(db, "analysis", project_id=project.id, owner_id=user.id, payload={"snapshot_id": project.latest_snapshot_id})
    db.commit()
    return job


@router.get("/{project_id}/snapshots", response_model=list[SnapshotOut])
def snapshots(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(RepositorySnapshot).where(RepositorySnapshot.project_id == project.id)
                      .order_by(RepositorySnapshot.id.desc())).all()


@router.get("/{project_id}/files")
def list_files(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    snap = db.get(RepositorySnapshot, project.latest_snapshot_id) if project.latest_snapshot_id else None
    if not snap:
        return {"files": [], "snapshot_id": None}
    root = snapshot_root(snap)
    files = [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size}
             for p in sorted(root.rglob("*")) if p.is_file()][:5000]
    return {"files": files, "snapshot_id": snap.id}


@router.get("/{project_id}/files/content")
def file_content(path: str = Query(max_length=500), project: Project = Depends(get_project), db: Session = Depends(get_db)):
    snap = db.get(RepositorySnapshot, project.latest_snapshot_id) if project.latest_snapshot_id else None
    if not snap:
        raise HTTPException(404, "No snapshot")
    root = snapshot_root(snap)
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "File not found")
    if target.stat().st_size > 256 * 1024:
        raise HTTPException(413, "File too large to display")
    try:
        return {"path": path, "content": target.read_text(encoding="utf-8")}
    except UnicodeDecodeError as exc:
        raise HTTPException(415, "Binary file") from exc


@router.get("/{project_id}/jobs", response_model=list[JobOut])
def project_jobs(project: Project = Depends(get_project), db: Session = Depends(get_db), limit: int = Query(30, le=100)):
    return db.scalars(select(Job).where(Job.project_id == project.id).order_by(Job.id.desc()).limit(limit)).all()


def _job_for_user(job_id: int, user: User, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.project_id:
        p = db.get(Project, job.project_id)
        if p is None or p.workspace_id not in workspace_ids_for(db, user):
            raise HTTPException(404, "Job not found")
    elif job.owner_id != user.id:
        raise HTTPException(404, "Job not found")
    return job


@jobs_router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _job_for_user(job_id, user, db)


@jobs_router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _job_for_user(job_id, user, db)
    if job.status == "queued":
        job.status, job.cancel_requested = "cancelled", True
        if job.job_type == "execution":
            run = db.get(TestRun, job.payload.get("run_id"))
            if run:
                run.status = "cancelled"
    elif job.status in ("preparing", "running"):
        job.cancel_requested = True  # worker observes the flag and stops the sandbox
    else:
        raise HTTPException(409, f"Job already finished ({job.status})")
    db.commit()
    return job
