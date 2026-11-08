"""Analysis results, findings, test generation and review."""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, get_project
from app.database.session import get_db
from app.generators.js_tests import validate_js_test
from app.generators.python_tests import validate_python_test
from app.models import Finding, GeneratedTest, Project, RepositoryAnalysis, User, utcnow
from app.schemas.api import (
    AnalysisOut,
    BulkReviewIn,
    FindingOut,
    FindingUpdate,
    GeneratedTestOut,
    GeneratedTestUpdate,
    GenerateIn,
    JobOut,
    Page,
)
from app.services.analysis_service import latest_analysis
from app.services.execution_service import generated_filename
from app.services.jobs import enqueue, log_activity

router = APIRouter(prefix="/api/projects/{project_id}", tags=["analysis & generation"])
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@router.get("/analysis", response_model=AnalysisOut | None)
def get_analysis(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return latest_analysis(db, project.id)


@router.get("/analyses", response_model=list[dict])
def analysis_history(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.scalars(select(RepositoryAnalysis).where(RepositoryAnalysis.project_id == project.id)
                      .order_by(RepositoryAnalysis.id.desc()).limit(50)).all()
    out = []
    for a in rows:
        counts = dict(db.execute(select(Finding.severity, func.count()).where(Finding.analysis_id == a.id)
                                 .group_by(Finding.severity)).all())
        out.append({"id": a.id, "created_at": a.created_at.isoformat(), "files_inspected": a.files_inspected,
                    "findings_by_severity": counts, "duration_ms": a.duration_ms})
    return out


@router.get("/findings", response_model=Page[FindingOut])
def list_findings(severity: str | None = Query(None, max_length=15), status: str | None = Query(None, max_length=20),
                  category: str | None = Query(None, max_length=40), q: str | None = Query(None, max_length=100),
                  analysis_id: int | None = None, pg: Pagination = Depends(),
                  project: Project = Depends(get_project), db: Session = Depends(get_db)):
    a = db.get(RepositoryAnalysis, analysis_id) if analysis_id else latest_analysis(db, project.id)
    if a is None or a.project_id != project.id:
        return Page(items=[], total=0, page=pg.page, page_size=pg.page_size)
    stmt = select(Finding).where(Finding.analysis_id == a.id)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    if status:
        stmt = stmt.where(Finding.status == status)
    if category:
        stmt = stmt.where(Finding.category == category)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Finding.title).like(like) | func.lower(Finding.file_path).like(like))
    rows = db.scalars(stmt).all()
    rows = sorted(rows, key=lambda f: (SEV_ORDER.get(f.severity, 9), f.file_path, f.line or 0))
    return Page(items=rows[pg.offset: pg.offset + pg.page_size], total=len(rows), page=pg.page, page_size=pg.page_size)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def update_finding(finding_id: int, body: FindingUpdate, project: Project = Depends(get_project),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(Finding, finding_id)
    if f is None or f.project_id != project.id:
        raise HTTPException(404, "Finding not found")
    f.status = body.status
    log_activity(db, project, user.id, "finding.status", f"{f.rule_id} → {body.status}")
    db.commit()
    return f


@router.post("/generate", response_model=JobOut, status_code=202)
def generate(body: GenerateIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    if not latest_analysis(db, project.id):
        raise HTTPException(400, "Run repository analysis before generating tests")
    job = enqueue(db, "generation", project_id=project.id, owner_id=user.id, payload=body.model_dump())
    db.commit()
    return job


@router.get("/generated-tests", response_model=Page[GeneratedTestOut])
def list_generated(status: str | None = Query(None, max_length=20), language: str | None = Query(None, max_length=20),
                   category: str | None = Query(None, max_length=30), pg: Pagination = Depends(),
                   project: Project = Depends(get_project), db: Session = Depends(get_db)):
    stmt = select(GeneratedTest).where(GeneratedTest.project_id == project.id)
    if status:
        stmt = stmt.where(GeneratedTest.status == status)
    if language:
        stmt = stmt.where(GeneratedTest.language == language)
    if category:
        stmt = stmt.where(GeneratedTest.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(GeneratedTest.target_file, GeneratedTest.id).offset(pg.offset).limit(pg.page_size)).all()
    return Page(items=rows, total=total or 0, page=pg.page, page_size=pg.page_size)


def _test(project: Project, test_id: int, db: Session) -> GeneratedTest:
    t = db.get(GeneratedTest, test_id)
    if t is None or t.project_id != project.id:
        raise HTTPException(404, "Generated test not found")
    return t


@router.patch("/generated-tests/{test_id}", response_model=GeneratedTestOut)
def update_generated(test_id: int, body: GeneratedTestUpdate, project: Project = Depends(get_project),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _test(project, test_id, db)
    if body.code is not None and body.code != t.code:
        t.code = body.code
        t.validation = {**(validate_python_test(t.code) if t.language == "Python" else validate_js_test(t.code)),
                        "strategy": t.validation.get("strategy"), "edited_by_user": True}
        if t.status == "approved":
            t.status = "proposed"  # edited code must be re-approved
    if body.status is not None:
        if body.status == "approved" and (not t.validation.get("syntax_ok") or t.validation.get("forbidden_calls")):
            raise HTTPException(422, "This test failed validation and cannot be approved until it is fixed")
        t.status = body.status
        t.reviewed_by, t.reviewed_at = user.id, utcnow()
        log_activity(db, project, user.id, f"test.{body.status}", t.name)
    db.commit()
    return t


@router.post("/generated-tests/review", response_model=dict)
def bulk_review(body: BulkReviewIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    tests = db.scalars(select(GeneratedTest).where(GeneratedTest.id.in_(body.ids), GeneratedTest.project_id == project.id)).all()
    changed, skipped = 0, []
    for t in tests:
        if body.status == "approved" and (not t.validation.get("syntax_ok") or t.validation.get("forbidden_calls")):
            skipped.append(t.id)
            continue
        t.status, t.reviewed_by, t.reviewed_at = body.status, user.id, utcnow()
        changed += 1
    log_activity(db, project, user.id, f"test.bulk_{body.status}", f"{changed} tests")
    db.commit()
    return {"updated": changed, "skipped_invalid": skipped}


@router.get("/generated-tests/export")
def export_approved(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Download approved tests as a zip so the user can add them to their own repository.
    TestPilot never writes to a connected repository."""
    tests = db.scalars(select(GeneratedTest).where(GeneratedTest.project_id == project.id,
                                                   GeneratedTest.status == "approved")).all()
    if not tests:
        raise HTTPException(404, "No approved tests to export")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in tests:
            zf.writestr(f"testpilot_generated/{generated_filename(t)}", t.code)
        zf.writestr("testpilot_generated/README.txt",
                    "Tests generated by TestPilot AI and approved by a reviewer.\n"
                    "Python tests expect the repository root on PYTHONPATH. JavaScript/TypeScript tests use Vitest globals.\n")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="testpilot-tests-{project.id}.zip"'})
