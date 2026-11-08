"""Creating repository snapshots (import jobs)."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.integrations.github import GitHubClient, validate_branch
from app.models import GitHubConnection, Job, Project, RepositorySnapshot
from app.services.archive import ExtractionResult, copy_tree, extract_archive
from app.services.jobs import enqueue, log_activity

log = logging.getLogger(__name__)


def snapshot_root(snapshot: RepositorySnapshot) -> Path:
    root = (Path(settings.storage_root) / snapshot.storage_path).resolve()
    base = Path(settings.storage_root).resolve()
    if not str(root).startswith(str(base)):
        raise ValueError("Snapshot path escapes storage root")
    return root


def _new_dir(project_id: int) -> tuple[str, Path]:
    rel = f"snapshots/{project_id}/{uuid.uuid4().hex}"
    path = Path(settings.storage_root) / rel
    path.mkdir(parents=True, exist_ok=False)
    return rel, path


def _limits() -> dict:
    return {"max_total_bytes": settings.max_extracted_size_mb * 1024 * 1024,
            "max_files": settings.max_files_per_snapshot}


def github_token_for(db: Session, user_id: int | None) -> str | None:
    if user_id:
        conn = db.query(GitHubConnection).filter_by(user_id=user_id).one_or_none()
        if conn:
            tok = decrypt_secret(conn.encrypted_token)
            if tok:
                return tok
    return settings.github_public_token


def handle_import(db: Session, job: Job) -> dict:
    project = db.get(Project, job.project_id)
    if project is None:
        raise ValueError("Project no longer exists")
    source = job.payload.get("source")
    project.status = "importing"
    db.commit()
    rel, dest = _new_dir(project.id)
    ref = sha = None
    try:
        if source == "demo":
            if not project.is_demo:
                raise ValueError("Demo import requested for a non-demo project")
            res: ExtractionResult = copy_tree(Path(settings.demo_project_path), dest, **_limits())
            ref = "demo"
        elif source == "archive":
            upload = Path(job.payload["upload_path"])
            base = (Path(settings.storage_root) / "uploads").resolve()
            if not str(upload.resolve()).startswith(str(base)):
                raise ValueError("Invalid upload path")
            try:
                data = upload.read_bytes()
                res = extract_archive(data, dest, **_limits())
            finally:
                upload.unlink(missing_ok=True)
            ref = "upload"
        elif source == "github":
            full = project.github_full_name
            ref = validate_branch(job.payload.get("ref") or project.default_branch or "main")
            client = GitHubClient(github_token_for(db, job.owner_id))
            try:
                sha = client.latest_commit(full, ref)["sha"]
            except Exception:  # commit metadata is best-effort
                sha = None
            data = client.download_tarball(full, sha or ref, settings.max_repository_size_mb * 1024 * 1024)
            res = extract_archive(data, dest, **_limits())
        else:
            raise ValueError(f"Unknown import source: {source}")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        project.status = "error"
        db.commit()
        raise
    snap = RepositorySnapshot(project_id=project.id, source=source, ref=ref, commit_sha=sha, storage_path=rel,
                              file_count=res.file_count, total_bytes=res.total_bytes, skipped=res.skipped[:200])
    db.add(snap)
    db.flush()
    project.latest_snapshot_id = snap.id
    project.status = "analysing"
    log_activity(db, project, job.owner_id, "snapshot.created",
                 f"Imported {res.file_count} files from {source}{f' @ {ref}' if ref else ''}")
    nxt = enqueue(db, "analysis", project_id=project.id, owner_id=job.owner_id, payload={"snapshot_id": snap.id})
    db.commit()
    return {"snapshot_id": snap.id, "files": res.file_count, "skipped": len(res.skipped), "analysis_job_id": nxt.id}
