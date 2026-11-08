"""Test execution, results, failure analysis, comparison and coverage."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.provider import AIUnavailable
from app.api.deps import Pagination, ai_limiter, get_current_user, get_project
from app.core.config import settings
from app.database.session import get_db
from app.execution.providers import ExecutionSpec, get_execution_provider
from app.models import CoverageReport, Finding, GeneratedTest, Project, TestResult, TestRun, User
from app.schemas.api import CoverageOut, Page, ResultOut, RunIn, RunOut
from app.services.analysis_service import latest_analysis
from app.services.assistant_service import ai_failure_analysis
from app.services.jobs import enqueue, log_activity
from app.services.snapshots import snapshot_root

router = APIRouter(prefix="/api/projects/{project_id}", tags=["test runs & coverage"])


def run_out(db: Session, r: TestRun) -> RunOut:
    out = RunOut.model_validate(r)
    cov = db.scalars(select(CoverageReport).where(CoverageReport.run_id == r.id)).first()
    if cov:
        out.coverage = {"line_percent": cov.line_percent, "branch_percent": cov.branch_percent,
                        "function_percent": cov.function_percent, "tool": cov.tool}
    return out


def _run(project: Project, run_id: int, db: Session) -> TestRun:
    r = db.get(TestRun, run_id)
    if r is None or r.project_id != project.id:
        raise HTTPException(404, "Test run not found")
    return r


@router.get("/execution/status")
def execution_status(project: Project = Depends(get_project)):
    provider = get_execution_provider()
    out = {"provider": provider.name, "isolation": provider.isolation}
    for lang in ("python", "javascript"):
        spec = ExecutionSpec(job_key="probe", language=lang, work_dir=Path("."), out_dir=Path("."),
                             include_existing=True, trusted_demo=project.is_demo)
        ok, reason = provider.availability(spec)
        out[lang] = {"available": ok, "reason": reason}
    return out


@router.post("/runs", response_model=RunOut, status_code=202)
def create_run(body: RunIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not project.latest_snapshot_id:
        raise HTTPException(400, "Import the project's code before running tests")
    ids = sorted(set(body.generated_test_ids))
    if ids:
        tests = db.scalars(select(GeneratedTest).where(GeneratedTest.id.in_(ids))).all()
        if len(tests) != len(ids) or any(t.project_id != project.id for t in tests):
            raise HTTPException(404, "One or more generated tests were not found")
        not_approved = [t.id for t in tests if t.status != "approved"]
        if not_approved:
            raise HTTPException(422, f"Generated tests must be approved before execution: {not_approved}")
        lang_family = "Python" if body.language == "Python" else "JS"
        mismatched = [t.id for t in tests if ("Python" if t.language == "Python" else "JS") != lang_family]
        if mismatched:
            raise HTTPException(422, f"Tests {mismatched} are not {body.language} tests")
    elif not body.include_existing:
        raise HTTPException(422, "Select approved generated tests or include the project's existing tests")
    run = TestRun(project_id=project.id, snapshot_id=project.latest_snapshot_id, created_by=user.id,
                  language="Python" if body.language == "Python" else "JavaScript",
                  framework="pytest" if body.language == "Python" else "vitest",
                  provider=get_execution_provider().name, include_existing=body.include_existing,
                  generated_test_ids=ids, status="queued")
    db.add(run)
    db.flush()
    job = enqueue(db, "execution", project_id=project.id, owner_id=user.id, payload={"run_id": run.id}, max_attempts=1)
    run.job_id = job.id
    log_activity(db, project, user.id, "run.queued", f"Run #{run.id} ({body.language}, {len(ids)} generated tests)")
    db.commit()
    return run_out(db, run)


@router.get("/runs", response_model=Page[RunOut])
def list_runs(pg: Pagination = Depends(), status: str | None = Query(None, max_length=30),
              project: Project = Depends(get_project), db: Session = Depends(get_db)):
    stmt = select(TestRun).where(TestRun.project_id == project.id)
    if status:
        stmt = stmt.where(TestRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(TestRun.id.desc()).offset(pg.offset).limit(pg.page_size)).all()
    return Page(items=[run_out(db, r) for r in rows], total=total, page=pg.page, page_size=pg.page_size)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return run_out(db, _run(project, run_id, db))


@router.get("/runs/{run_id}/results", response_model=list[ResultOut])
def run_results(run_id: int, status: str | None = Query(None, max_length=15), project: Project = Depends(get_project),
                db: Session = Depends(get_db)):
    _run(project, run_id, db)
    stmt = select(TestResult).where(TestResult.run_id == run_id)
    if status:
        stmt = stmt.where(TestResult.status == status)
    order = {"error": 0, "failed": 1, "skipped": 2, "passed": 3}
    return sorted(db.scalars(stmt).all(), key=lambda r: (order.get(r.status, 9), r.node_id))


@router.get("/runs/{run_id}/log", response_class=PlainTextResponse)
def run_log(run_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    r = _run(project, run_id, db)
    if not r.log_path:
        raise HTTPException(404, "No log was recorded for this run")
    p = (Path(settings.storage_root) / r.log_path).resolve()
    if not str(p).startswith(str(Path(settings.storage_root).resolve())) or not p.exists():
        raise HTTPException(404, "Log file is no longer available (storage may be ephemeral)")
    return p.read_text(encoding="utf-8", errors="replace")[-200_000:]


@router.post("/results/{result_id}/ai-analysis", response_model=ResultOut, dependencies=[Depends(ai_limiter)])
def analyse_result(result_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    res = db.get(TestResult, result_id)
    run = db.get(TestRun, res.run_id) if res else None
    if res is None or run is None or run.project_id != project.id:
        raise HTTPException(404, "Result not found")
    if res.status not in ("failed", "error"):
        raise HTTPException(400, "Only failed or errored tests can be analysed")
    excerpt = None
    loc = (res.rule_analysis or {}).get("location")
    if loc and project.latest_snapshot_id:
        from app.models import RepositorySnapshot
        snap = db.get(RepositorySnapshot, run.snapshot_id)
        try:
            root = snapshot_root(snap)
            target = (root / loc["file"]).resolve()
            if str(target).startswith(str(root)) and target.is_file():
                lines = target.read_text(encoding="utf-8").splitlines()
                lo = max(0, loc["line"] - 15)
                excerpt = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[lo: loc["line"] + 10], start=lo))
        except (OSError, UnicodeDecodeError, ValueError):
            excerpt = None
    try:
        res.ai_analysis = ai_failure_analysis(db, res, excerpt)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    log_activity(db, project, user.id, "result.ai_analysis", res.name)
    db.commit()
    return res


@router.get("/runs/compare/{base_id}/{head_id}")
def compare(base_id: int, head_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    base, head = _run(project, base_id, db), _run(project, head_id, db)
    def results(r):
        return {x.node_id: x.status for x in db.scalars(select(TestResult).where(TestResult.run_id == r.id))}
    b, h = results(base), results(head)
    common = set(b) & set(h)
    regressions = sorted(n for n in common if b[n] == "passed" and h[n] in ("failed", "error"))
    fixed = sorted(n for n in common if b[n] in ("failed", "error") and h[n] == "passed")
    cov = {r.id: db.scalars(select(CoverageReport).where(CoverageReport.run_id == r.id)).first() for r in (base, head)}
    def cov_val(r):
        c = cov[r.id]
        return c.line_percent if c else None
    def counts(r):
        return {"status": r.status, "total": r.total, "passed": r.passed, "failed": r.failed, "errors": r.errors,
                "skipped": r.skipped, "duration_seconds": r.duration_seconds, "line_coverage": cov_val(r),
                "snapshot_id": r.snapshot_id, "created_at": r.created_at.isoformat()}
    comparable = bool(common)
    same_tool = (cov[base.id] is not None and cov[head.id] is not None
                 and cov[base.id].tool.split(" ")[0] == cov[head.id].tool.split(" ")[0])
    cov_delta = round(cov_val(head) - cov_val(base), 2) if same_tool else None  # never compare across tools
    # Findings delta between the analyses closest to each run's snapshot
    from app.models import RepositoryAnalysis
    def fps(snapshot_id):
        a = db.scalars(select(RepositoryAnalysis).where(RepositoryAnalysis.snapshot_id == snapshot_id)
                       .order_by(RepositoryAnalysis.id.desc()).limit(1)).first()
        if not a:
            return None
        return {f.fingerprint: f.title for f in db.scalars(select(Finding).where(Finding.analysis_id == a.id))}
    fb, fh = fps(base.snapshot_id), fps(head.snapshot_id)
    findings = None
    if fb is not None and fh is not None:
        findings = {"new": [fh[k] for k in fh.keys() - fb.keys()][:50], "resolved": [fb[k] for k in fb.keys() - fh.keys()][:50],
                    "same_snapshot": base.snapshot_id == head.snapshot_id}
    return {
        "base": {"id": base.id, **counts(base)}, "head": {"id": head.id, **counts(head)},
        "comparable": comparable, "common_tests": len(common),
        "regressions": regressions, "fixed": fixed,
        "new_tests": sorted(set(h) - set(b))[:200], "removed_tests": sorted(set(b) - set(h))[:200],
        "coverage_delta": cov_delta, "findings": findings,
        "note": None if comparable else "The runs share no test IDs, so regressions cannot be determined.",
    }


@router.get("/coverage", response_model=list[CoverageOut])
def coverage_history(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(CoverageReport).where(CoverageReport.project_id == project.id)
                      .order_by(CoverageReport.id.desc()).limit(50)).all()


@router.get("/coverage/latest", response_model=CoverageOut | None)
def coverage_latest(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    cov = db.scalars(select(CoverageReport).where(CoverageReport.project_id == project.id)
                     .order_by(CoverageReport.id.desc()).limit(1)).first()
    return cov


@router.get("/coverage/untested")
def untested(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Supported source files absent from the latest coverage report (never imported during the run)."""
    cov = db.scalars(select(CoverageReport).where(CoverageReport.project_id == project.id)
                     .order_by(CoverageReport.id.desc()).limit(1)).first()
    a = latest_analysis(db, project.id)
    if not cov or not a:
        return {"measured": False, "files": []}
    covered = {f["path"] for f in cov.files}
    run = db.get(TestRun, cov.run_id)
    ext = (".py",) if run and run.language == "Python" else (".js", ".ts", ".mjs", ".tsx", ".jsx")
    srcs = [p for p in a.summary.get("symbols", {}) if p.endswith(ext)]
    return {"measured": True, "run_id": cov.run_id, "files": sorted(p for p in srcs if p not in covered)}
