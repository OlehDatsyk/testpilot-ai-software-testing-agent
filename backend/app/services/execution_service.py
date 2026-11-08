"""Test execution job: prepare workspace → provider → parse artefacts → store.

Statuses written to TestRun come only from what actually happened:
queued → preparing → running → passed | failed | partially_passed | timed_out |
cancelled | execution_unavailable | infrastructure_error
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.execution.failure_analysis import analyse_failure
from app.execution.providers import ExecutionSpec, get_execution_provider
from app.execution.results import ArtefactError, parse_junit, parse_python_coverage, parse_vitest_coverage
from app.models import CoverageReport, GeneratedTest, Job, Project, RepositorySnapshot, TestResult, TestRun, utcnow
from app.services.archive import copy_tree
from app.services.jobs import is_cancel_requested, log_activity, set_status
from app.services.snapshots import snapshot_root

log = logging.getLogger(__name__)
GEN_DIR = "testpilot_generated"
GEN_FILE_RE = re.compile(r"tp_(\d+)_")


def generated_filename(t: GeneratedTest) -> str:
    slug = re.sub(r"\W+", "_", t.name).strip("_").lower()[:40] or "test"
    if t.language == "Python":
        return f"test_tp_{t.id}_{slug}.py"
    ext = "ts" if t.target_file.endswith((".ts", ".tsx", ".mts")) else "js"
    return f"tp_{t.id}_{slug}.test.{ext}"


def prepare_workspace(snap: RepositorySnapshot, tests: list[GeneratedTest], job_dir: Path) -> tuple[Path, Path]:
    work, out = job_dir / "work", job_dir / "out"
    if job_dir.exists():
        shutil.rmtree(job_dir)
    copy_tree(snapshot_root(snap), work, max_files=settings.max_files_per_snapshot,
              max_total_bytes=settings.max_extracted_size_mb * 1024 * 1024)
    out.mkdir(parents=True)
    if tests:
        gen = work / GEN_DIR
        gen.mkdir(exist_ok=True)
        for t in tests:
            (gen / generated_filename(t)).write_text(t.code, encoding="utf-8")
    return work, out


def _final_status(passed: int, failed: int, errors: int, total: int) -> str:
    if total == 0:
        return "failed"
    if failed + errors == 0:
        return "passed"
    return "partially_passed" if passed > 0 else "failed"


def handle_execution(db: Session, job: Job) -> dict:
    run = db.get(TestRun, job.payload["run_id"])
    project = db.get(Project, job.project_id)
    snap = db.get(RepositorySnapshot, run.snapshot_id) if run else None
    if not run or not project or not snap:
        raise ValueError("Test run, project or snapshot missing")
    if job.cancel_requested:
        run.status = "cancelled"
        set_status(db, job, "cancelled")
        return {"status": "cancelled"}

    provider = get_execution_provider()
    run.provider = provider.name
    lang = "python" if run.language == "Python" else "javascript"
    job_dir = Path(settings.storage_root) / "runs" / str(run.id)
    spec = ExecutionSpec(job_key=f"run{run.id}-{job.attempts}", language=lang, work_dir=job_dir / "work",
                         out_dir=job_dir / "out", include_existing=run.include_existing, coverage=True,
                         timeout=settings.execution_timeout, trusted_demo=project.is_demo)
    ok, reason = provider.availability(spec)
    if not ok:
        run.status, run.error_message, run.finished_at = "execution_unavailable", reason, utcnow()
        log_activity(db, project, job.owner_id, "run.unavailable", reason)
        set_status(db, job, "execution_unavailable", error=reason)
        return {"status": "execution_unavailable", "reason": reason}

    run.status = "preparing"
    set_status(db, job, "preparing")
    tests = [db.get(GeneratedTest, i) for i in run.generated_test_ids]
    tests = [t for t in tests if t is not None and t.status == "approved" and t.project_id == project.id]
    try:
        work, out = prepare_workspace(snap, tests, job_dir)
        run.status, run.started_at = "running", utcnow()
        set_status(db, job, "running")
        outcome = provider.run(spec, lambda: is_cancel_requested(db, job.id))
        run.duration_seconds = round(outcome.duration_seconds, 3)
        run.exit_code = outcome.exit_code
        if outcome.status in ("cancelled", "timed_out", "infrastructure_error", "unavailable"):
            final = {"unavailable": "execution_unavailable"}.get(outcome.status, outcome.status)
            run.status, run.error_message, run.finished_at = final, outcome.message, utcnow()
            _store_log(run, out)
            log_activity(db, project, job.owner_id, f"run.{final}", outcome.message or "")
            set_status(db, job, final, error=outcome.message)
            return {"status": final}

        runner_meta = {}
        if (out / "runner.json").exists():
            runner_meta = json.loads((out / "runner.json").read_text(encoding="utf-8"))
        if runner_meta.get("timed_out"):
            run.status, run.error_message = "timed_out", f"Tests exceeded the {settings.execution_timeout}s limit"
        artefact_error = None
        try:
            parsed = parse_junit(out / "junit.xml")
        except ArtefactError as exc:
            parsed, artefact_error = [], str(exc)
        id_by_file = {generated_filename(t): t.id for t in tests}
        counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
        for r in parsed:
            counts[r.status] = counts.get(r.status, 0) + 1
            gen_id = None
            ident = f"{r.file_path or ''} {r.classname or ''}"
            m = GEN_FILE_RE.search(ident)
            if m:
                gen_id = int(m.group(1)) if int(m.group(1)) in id_by_file.values() else None
            analysis = analyse_failure(r.message, r.traceback, lang) if r.status in ("failed", "error") else None
            db.add(TestResult(run_id=run.id, node_id=r.node_id, name=r.name, file_path=r.file_path,
                              classname=r.classname, status=r.status, duration_seconds=r.duration, message=r.message,
                              traceback=r.traceback, generated_test_id=gen_id, rule_analysis=analysis))
        run.total = len(parsed)
        run.passed, run.failed, run.errors, run.skipped = counts["passed"], counts["failed"], counts["error"], counts["skipped"]
        if run.status != "timed_out":
            run.status = _final_status(run.passed, run.failed, run.errors, run.total)
            if run.total == 0:
                run.error_message = ("No test results were produced"
                                     + (f" ({artefact_error})" if artefact_error else "")
                                     + ". See the run log for collection or import errors.")
        _store_coverage(db, run, project, out, lang, work)
        _store_log(run, out)
        run.finished_at = utcnow()
        log_activity(db, project, job.owner_id, "run.completed",
                     f"Run #{run.id}: {run.passed} passed, {run.failed} failed, {run.errors} errors, {run.skipped} skipped")
        set_status(db, job, "succeeded", result={"run_status": run.status, "total": run.total})
        return {"status": run.status}
    finally:
        shutil.rmtree(job_dir / "work", ignore_errors=True)


def _store_coverage(db: Session, run: TestRun, project: Project, out: Path, lang: str, work: Path) -> None:
    try:
        cov = (parse_python_coverage(out / "coverage.json") if lang == "python"
               else parse_vitest_coverage(out / "coverage" / "coverage-summary.json"))
    except (ArtefactError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Coverage artefact rejected for run %s: %s", run.id, exc)
        cov = None
    if not cov or cov.get("lines_total") in (None, 0):
        return
    prefix = str(work.resolve()).replace("\\", "/").rstrip("/") + "/"
    for f in cov["files"]:
        if f["path"].startswith(prefix):
            f["path"] = f["path"][len(prefix):]
    db.add(CoverageReport(run_id=run.id, project_id=project.id, tool=cov["tool"], line_percent=cov["line_percent"],
                          branch_percent=cov["branch_percent"], function_percent=cov["function_percent"],
                          lines_covered=cov["lines_covered"], lines_total=cov["lines_total"], files=cov["files"]))


def _store_log(run: TestRun, out: Path) -> None:
    p = out / "output.log"
    if p.exists():
        run.log_path = str(p.relative_to(Path(settings.storage_root))).replace("\\", "/")
