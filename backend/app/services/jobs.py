"""Database-backed job queue.

Jobs are rows in the ``jobs`` table. The worker process claims a job with an
atomic conditional UPDATE (works on SQLite and PostgreSQL), holds a lease while
processing, and records the final state. Expired leases are re-queued until
``max_attempts`` is reached. No fake progress: the only states reported are
the ones actually recorded.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Activity, Job, Project, utcnow

ACTIVE = ("queued", "preparing", "running")
TERMINAL = ("succeeded", "failed", "cancelled", "timed_out", "execution_unavailable", "infrastructure_error")


def enqueue(db: Session, job_type: str, *, project_id: int | None, owner_id: int | None, payload: dict | None = None,
            max_attempts: int | None = None) -> Job:
    job = Job(job_type=job_type, project_id=project_id, owner_id=owner_id, payload=payload or {}, status="queued",
              max_attempts=max_attempts or settings.job_max_attempts)
    db.add(job)
    db.flush()
    return job


def requeue_expired(db: Session) -> int:
    now = utcnow()
    expired = db.scalars(select(Job).where(Job.status.in_(("preparing", "running")), Job.lease_until < now)).all()
    for job in expired:
        if job.attempts >= job.max_attempts:
            job.status, job.error, job.finished_at = "failed", "Worker lease expired; maximum attempts reached", now
        else:
            job.status, job.worker_id, job.lease_until = "queued", None, None
    if expired:
        db.commit()
    return len(expired)


def claim_next(db: Session, worker_id: str, job_types: tuple[str, ...] | None = None) -> Job | None:
    requeue_expired(db)
    q = select(Job.id).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(5)
    if job_types:
        q = q.where(Job.job_type.in_(job_types))
    for job_id in db.scalars(q).all():
        now = utcnow()
        res = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="preparing", worker_id=worker_id, attempts=Job.attempts + 1, started_at=now,
                    lease_until=now + timedelta(seconds=settings.job_lease_seconds))
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Job, job_id)
    return None


def set_status(db: Session, job: Job, status: str, *, error: str | None = None, result: dict | None = None) -> None:
    job.status = status
    if error is not None:
        job.error = error[:4000]
    if result is not None:
        job.result = result
    if status in TERMINAL:
        job.finished_at = utcnow()
        job.lease_until = None
    else:
        job.lease_until = utcnow() + timedelta(seconds=settings.job_lease_seconds)
    db.commit()


def is_cancel_requested(db: Session, job_id: int) -> bool:
    val = db.execute(select(Job.cancel_requested).where(Job.id == job_id)).scalar_one_or_none()
    return bool(val)


def log_activity(db: Session, project: Project | None, user_id: int | None, action: str, detail: str = "",
                 workspace_id: int | None = None) -> None:
    db.add(Activity(workspace_id=workspace_id or (project.workspace_id if project else None),
                    project_id=project.id if project else None, user_id=user_id, action=action, detail=detail[:500]))
