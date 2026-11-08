"""Dashboard and analytics — every figure is computed from stored records."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, workspace_ids_for
from app.database.session import get_db
from app.models import (
    Activity,
    CoverageReport,
    Finding,
    GeneratedTest,
    Project,
    RepositoryAnalysis,
    TestResult,
    TestRun,
    User,
    utcnow,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _latest_analysis_ids(db: Session, project_ids: list[int]) -> list[int]:
    if not project_ids:
        return []
    rows = db.execute(select(func.max(RepositoryAnalysis.id)).where(RepositoryAnalysis.project_id.in_(project_ids))
                      .group_by(RepositoryAnalysis.project_id)).all()
    return [r[0] for r in rows]


@router.get("/overview")
def overview(project_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pids = list(db.scalars(select(Project.id).where(Project.workspace_id.in_(workspace_ids_for(db, user)))))
    if project_id is not None:
        pids = [p for p in pids if p == project_id]
    demo_ids = set(db.scalars(select(Project.id).where(Project.id.in_(pids), Project.is_demo.is_(True)))) if pids else set()
    la = _latest_analysis_ids(db, pids)
    run_ids = list(db.scalars(select(TestRun.id).where(TestRun.project_id.in_(pids)))) if pids else []
    result_counts = dict(db.execute(select(TestResult.status, func.count()).where(TestResult.run_id.in_(run_ids))
                                    .group_by(TestResult.status)).all()) if run_ids else {}
    open_by_sev = dict(db.execute(select(Finding.severity, func.count()).where(Finding.analysis_id.in_(la),
                                                                              Finding.status == "open")
                                  .group_by(Finding.severity)).all()) if la else {}
    recent_runs = db.scalars(select(TestRun).where(TestRun.project_id.in_(pids)).order_by(TestRun.id.desc()).limit(8)).all() if pids else []
    names = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(pids))).all()) if pids else {}
    activity = db.scalars(select(Activity).where(Activity.workspace_id.in_(workspace_ids_for(db, user)))
                          .order_by(Activity.id.desc()).limit(15)).all()
    return {
        "projects": len(pids),
        "demo_projects": len(demo_ids),
        "repositories_analysed": db.scalar(select(func.count(func.distinct(RepositoryAnalysis.project_id)))
                                           .where(RepositoryAnalysis.project_id.in_(pids))) if pids else 0,
        "tests_generated": db.scalar(select(func.count()).select_from(GeneratedTest).where(GeneratedTest.project_id.in_(pids))) if pids else 0,
        "tests_approved": db.scalar(select(func.count()).select_from(GeneratedTest).where(
            GeneratedTest.project_id.in_(pids), GeneratedTest.status == "approved")) if pids else 0,
        "test_runs": len(run_ids),
        "tests_executed": sum(result_counts.values()),
        "passed": result_counts.get("passed", 0),
        "failed": result_counts.get("failed", 0),
        "errors": result_counts.get("error", 0),
        "skipped": result_counts.get("skipped", 0),
        "open_findings": sum(open_by_sev.values()),
        "open_findings_by_severity": open_by_sev,
        "recent_runs": [{"id": r.id, "project_id": r.project_id, "project": names.get(r.project_id), "status": r.status,
                         "passed": r.passed, "failed": r.failed, "errors": r.errors, "total": r.total,
                         "is_demo": r.project_id in demo_ids, "created_at": r.created_at.isoformat(),
                         "duration_seconds": r.duration_seconds} for r in recent_runs],
        "recent_activity": [{"id": a.id, "action": a.action, "detail": a.detail, "project_id": a.project_id,
                             "project": names.get(a.project_id), "created_at": a.created_at.isoformat()} for a in activity],
    }


@router.get("/trends")
def trends(days: int = Query(30, ge=1, le=365), project_id: int | None = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    pids = list(db.scalars(select(Project.id).where(Project.workspace_id.in_(workspace_ids_for(db, user)))))
    if project_id is not None:
        pids = [p for p in pids if p == project_id]
    since = utcnow() - timedelta(days=days)
    buckets: dict[str, dict] = defaultdict(lambda: {"generated": 0, "executed": 0, "passed": 0, "failed": 0, "runs": 0})
    if pids:
        for t in db.scalars(select(GeneratedTest.created_at).where(GeneratedTest.project_id.in_(pids), GeneratedTest.created_at >= since)):
            buckets[t.date().isoformat()]["generated"] += 1
        runs = db.scalars(select(TestRun).where(TestRun.project_id.in_(pids), TestRun.created_at >= since)).all()
        durations = []
        for r in runs:
            d = buckets[r.created_at.date().isoformat()]
            d["runs"] += 1
            d["executed"] += r.total
            d["passed"] += r.passed
            d["failed"] += r.failed + r.errors
            if r.duration_seconds is not None:
                durations.append(r.duration_seconds)
        cov = db.execute(select(CoverageReport.created_at, CoverageReport.line_percent, CoverageReport.project_id, CoverageReport.run_id)
                         .where(CoverageReport.project_id.in_(pids), CoverageReport.created_at >= since)
                         .order_by(CoverageReport.created_at)).all()
        la = _latest_analysis_ids(db, pids)
        status_counts = dict(db.execute(select(Finding.status, func.count()).where(Finding.analysis_id.in_(la))
                                        .group_by(Finding.status)).all()) if la else {}
        activity = dict(db.execute(select(Project.name, func.count(Activity.id)).join(Activity, Activity.project_id == Project.id)
                                   .where(Project.id.in_(pids), Activity.created_at >= since).group_by(Project.name)).all())
    else:
        durations, cov, status_counts, activity = [], [], {}, {}
    return {
        "days": days,
        "daily": [{"date": k, **v} for k, v in sorted(buckets.items())],
        "coverage": [{"date": c[0].isoformat(), "line_percent": c[1], "project_id": c[2], "run_id": c[3]} for c in cov],
        "average_run_duration_seconds": round(sum(durations) / len(durations), 2) if durations else None,
        "findings_by_status": status_counts,
        "activity_by_project": [{"project": k, "events": v} for k, v in activity.items()],
    }
