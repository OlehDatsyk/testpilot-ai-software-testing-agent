"""TestPilot background worker.

Run with:  python -m app.worker

Claims queued jobs from the database and processes them one at a time. Test
execution is delegated to the configured ExecutionProvider (e.g. the Docker
sandbox); this process itself never imports or executes repository code.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback

from app import models  # noqa: F401
from app.core.config import settings
from app.core.logging import configure_logging
from app.database.session import Base, SessionLocal, engine
from app.integrations.github import GitHubError
from app.models import Job, Project, Report, TestRun, utcnow
from app.reporting.report_service import handle_report
from app.services.analysis_service import handle_analysis
from app.services.execution_service import handle_execution
from app.services.generation_service import handle_generation
from app.services.jobs import claim_next, set_status
from app.services.snapshots import handle_import

configure_logging()
log = logging.getLogger("testpilot.worker")

HANDLERS = {
    "import": handle_import,
    "analysis": handle_analysis,
    "generation": handle_generation,
    "execution": handle_execution,
    "report": handle_report,
}
_stop = False


def _graceful(*_):
    global _stop
    _stop = True
    log.info("Shutdown requested; finishing current job")


def process(job: Job) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job.id)
        handler = HANDLERS.get(job.job_type)
        if handler is None:
            set_status(db, job, "failed", error=f"Unknown job type {job.job_type}")
            return
        if job.job_type != "execution":
            set_status(db, job, "running")
        try:
            result = handler(db, job)
            db.refresh(job)
            if job.status not in ("succeeded", "failed", "cancelled", "timed_out", "execution_unavailable",
                                  "infrastructure_error"):
                set_status(db, job, "succeeded", result=result or {})
        except Exception as exc:  # job failed — record, maybe retry
            db.rollback()
            job = db.get(Job, job.id)
            msg = f"{type(exc).__name__}: {exc}"
            log.error("Job %s (%s) failed: %s\n%s", job.id, job.job_type, msg, traceback.format_exc(limit=5))
            # Only transient failures are retried; invalid input (ValueError incl. ArchiveError) is final.
            permanent = isinstance(exc, ValueError) or (isinstance(exc, GitHubError) and exc.status in (401, 403, 404))
            retryable = job.job_type in ("import", "report") and job.attempts < job.max_attempts and not permanent
            if retryable:
                job.status, job.error, job.lease_until = "queued", msg[:4000], None
                db.commit()
                return
            set_status(db, job, "failed", error=msg)
            _mark_related_failed(db, job, msg)


def _mark_related_failed(db, job: Job, msg: str) -> None:
    if job.job_type == "execution":
        run = db.get(TestRun, job.payload.get("run_id"))
        if run and run.status in ("queued", "preparing", "running"):
            run.status, run.error_message, run.finished_at = "infrastructure_error", msg[:2000], utcnow()
    elif job.job_type == "report":
        rep = db.get(Report, job.payload.get("report_id"))
        if rep:
            rep.status = "failed"
    elif job.job_type in ("import", "analysis") and job.project_id:
        p = db.get(Project, job.project_id)
        if p:
            p.status = "error"
    db.commit()


def main() -> None:
    if settings.auto_create_tables and settings.is_sqlite:
        Base.metadata.create_all(engine)
    signal.signal(signal.SIGINT, _graceful)
    signal.signal(signal.SIGTERM, _graceful)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    log.info("Worker %s started (execution provider: %s)", worker_id, settings.execution_provider)

    class _Flag:
        def is_set(self):
            return _stop

        def wait(self, t):
            time.sleep(t)

    run_loop(_Flag(), worker_id)


def run_loop(stop, worker_id: str) -> None:
    """Poll for jobs until ``stop.is_set()``. Used by the worker process and the embedded API thread."""
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                job = claim_next(db, worker_id)
        except Exception:  # database temporarily unavailable — back off
            log.exception("Could not poll for jobs")
            stop.wait(settings.worker_poll_interval * 5)
            continue
        if job is None:
            stop.wait(settings.worker_poll_interval)
            continue
        log.info("Processing job %s (%s)", job.id, job.job_type)
        process(job)


def run_pending_once(max_jobs: int = 50) -> int:
    """Process queued jobs synchronously (used by tests and scripts)."""
    n = 0
    while n < max_jobs:
        with SessionLocal() as db:
            job = claim_next(db, "inline")
        if job is None:
            break
        process(job)
        n += 1
    return n


if __name__ == "__main__":
    main()
