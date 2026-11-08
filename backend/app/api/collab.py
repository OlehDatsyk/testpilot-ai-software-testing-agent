"""Bug reports, AI assistant and QA reports."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, ai_limiter, get_current_user, get_project
from app.core.config import settings
from app.database.session import get_db
from app.models import (
    BugReport,
    Conversation,
    ConversationMessage,
    Finding,
    Project,
    Report,
    TestResult,
    TestRun,
    User,
)
from app.schemas.api import (
    BugFromSourceIn,
    BugIn,
    BugOut,
    BugUpdate,
    ChatIn,
    ConversationOut,
    JobOut,
    MessageOut,
    Page,
    ReportIn,
    ReportOut,
)
from app.services.assistant_service import answer
from app.services.jobs import enqueue, log_activity

router = APIRouter(prefix="/api/projects/{project_id}", tags=["bugs, assistant, reports"])


# --- bug reports --------------------------------------------------------------------------
def _bug(project: Project, bug_id: int, db: Session) -> BugReport:
    b = db.get(BugReport, bug_id)
    if b is None or b.project_id != project.id:
        raise HTTPException(404, "Bug report not found")
    return b


@router.get("/bugs", response_model=Page[BugOut])
def list_bugs(status: str | None = Query(None, max_length=20), severity: str | None = Query(None, max_length=15),
              q: str | None = Query(None, max_length=100), pg: Pagination = Depends(),
              project: Project = Depends(get_project), db: Session = Depends(get_db)):
    stmt = select(BugReport).where(BugReport.project_id == project.id)
    if status:
        stmt = stmt.where(BugReport.status == status)
    if severity:
        stmt = stmt.where(BugReport.severity == severity)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(BugReport.title).like(like), func.lower(func.coalesce(BugReport.file_path, "")).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(BugReport.id.desc()).offset(pg.offset).limit(pg.page_size)).all()
    return Page(items=rows, total=total, page=pg.page, page_size=pg.page_size)


@router.post("/bugs", response_model=BugOut, status_code=201)
def create_bug(body: BugIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    b = BugReport(project_id=project.id, created_by=user.id, source_type="manual", **body.model_dump())
    db.add(b)
    log_activity(db, project, user.id, "bug.created", body.title)
    db.commit()
    return b


@router.post("/bugs/from-source", response_model=BugOut, status_code=201)
def create_bug_from_source(body: BugFromSourceIn, project: Project = Depends(get_project),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Prefill a bug report from evidence. Fields without evidence are left empty, never invented."""
    if body.source_type == "finding":
        f = db.get(Finding, body.source_id)
        if f is None or f.project_id != project.id:
            raise HTTPException(404, "Finding not found")
        b = BugReport(
            project_id=project.id, created_by=user.id, title=f.title[:300], file_path=f.file_path, line=f.line,
            severity=f.severity, category=f.category,
            description=f"{f.description}\n\nDetected by {f.method} rule {f.rule_id} ({f.certainty}).",
            actual_behaviour=None, expected_behaviour=None, reproduction_steps=None,
            error_output=f"Source line:\n{f.evidence}" if f.evidence else None,
            suggested_solution=f.suggestion, source_type="finding", source_id=f.id)
    else:
        r = db.get(TestResult, body.source_id)
        run = db.get(TestRun, r.run_id) if r else None
        if r is None or run is None or run.project_id != project.id:
            raise HTTPException(404, "Test result not found")
        ra = r.rule_analysis or {}
        loc = ra.get("location") or {}
        ai = r.ai_analysis
        b = BugReport(
            project_id=project.id, created_by=user.id, title=f"Test failure: {r.name}"[:300],
            file_path=loc.get("file") or r.file_path, line=loc.get("line"), severity="high" if r.status == "error" else "medium",
            category="test-failure", description=f"Test `{r.node_id}` {r.status} in run #{run.id} ({run.provider} provider).",
            reproduction_steps=(f"1. Check out snapshot #{run.snapshot_id}.\n2. Run the {run.framework} test `{r.node_id}`."),
            expected_behaviour=None, actual_behaviour=r.message, error_output=r.traceback,
            suggested_solution="\n".join(ra.get("suggested_fixes", [])) or None,
            ai_explanation=(json.dumps({k: ai[k] for k in ("summary", "likely_causes", "suggested_fixes") if k in ai}, indent=2)
                            if ai else None),
            source_type="test_result", source_id=r.id)
    db.add(b)
    log_activity(db, project, user.id, "bug.created", b.title)
    db.commit()
    return b


@router.get("/bugs/{bug_id}", response_model=BugOut)
def get_bug(bug_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return _bug(project, bug_id, db)


@router.patch("/bugs/{bug_id}", response_model=BugOut)
def update_bug(bug_id: int, body: BugUpdate, project: Project = Depends(get_project), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    b = _bug(project, bug_id, db)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    if body.status:
        log_activity(db, project, user.id, "bug.status", f"#{b.id} → {body.status}")
    db.commit()
    return b


@router.delete("/bugs/{bug_id}", status_code=204)
def delete_bug(bug_id: int, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    db.delete(_bug(project, bug_id, db))
    db.commit()


@router.get("/bugs/{bug_id}/export")
def export_bug(bug_id: int, format: str = Query("markdown", pattern="^(markdown|json)$"),
               project: Project = Depends(get_project), db: Session = Depends(get_db)):
    b = _bug(project, bug_id, db)
    data = {c: getattr(b, c) for c in ("id", "title", "file_path", "line", "severity", "category", "description",
                                         "reproduction_steps", "expected_behaviour", "actual_behaviour", "error_output",
                                         "suggested_solution", "ai_explanation", "notes", "status", "source_type")}
    data["project"] = project.name
    data["created_at"] = b.created_at.isoformat()
    if format == "json":
        return data
    def sec(title, val):
        return f"## {title}\n\n{val}\n\n" if val else f"## {title}\n\n_Not available — no evidence recorded._\n\n"
    md = (f"# {b.title}\n\n**Project:** {project.name}  \n**Severity:** {b.severity}  \n**Category:** {b.category}  \n"
          f"**Status:** {b.status}  \n**Location:** `{b.file_path or 'unknown'}{f':{b.line}' if b.line else ''}`  \n"
          f"**Created:** {b.created_at:%Y-%m-%d %H:%M UTC}\n\n"
          + sec("Description", b.description) + sec("Steps to reproduce", b.reproduction_steps)
          + sec("Expected behaviour", b.expected_behaviour) + sec("Actual behaviour", b.actual_behaviour)
          + (f"## Error output\n\n```\n{b.error_output}\n```\n\n" if b.error_output else "")
          + sec("Suggested solution", b.suggested_solution)
          + (f"## AI explanation (suggestion)\n\n```\n{b.ai_explanation}\n```\n\n" if b.ai_explanation else "")
          + (f"## Notes\n\n{b.notes}\n" if b.notes else ""))
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="bug-{b.id}.md"'})


# --- assistant -----------------------------------------------------------------------------
@router.get("/conversations", response_model=list[ConversationOut])
def conversations(project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Conversation).where(Conversation.project_id == project.id, Conversation.user_id == user.id)
                      .order_by(Conversation.id.desc()).limit(50)).all()


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def messages(conv_id: int, project: Project = Depends(get_project), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    c = db.get(Conversation, conv_id)
    if c is None or c.project_id != project.id or c.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return c.messages


@router.post("/assistant", response_model=dict, dependencies=[Depends(ai_limiter)])
def chat(body: ChatIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.project_id != project.id or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = Conversation(project_id=project.id, user_id=user.id, title=body.message[:80])
        db.add(conv)
        db.flush()
    history = [{"role": m.role, "content": m.content} for m in conv.messages]
    db.add(ConversationMessage(conversation_id=conv.id, role="user", content=body.message))
    text, provider, sources = answer(db, project, body.message, history)
    msg = ConversationMessage(conversation_id=conv.id, role="assistant", content=text, provider=provider, sources=sources)
    db.add(msg)
    db.commit()
    return {"conversation_id": conv.id, "message": MessageOut.model_validate(msg).model_dump(mode="json")}


# --- reports ---------------------------------------------------------------------------------
@router.get("/reports", response_model=list[ReportOut])
def list_reports(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.id.desc()).limit(100)).all()


@router.post("/reports", response_model=JobOut, status_code=202)
def create_report(body: ReportIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if body.run_id:
        r = db.get(TestRun, body.run_id)
        if r is None or r.project_id != project.id:
            raise HTTPException(404, "Run not found")
    rep = Report(project_id=project.id, created_by=user.id, title=body.title or f"QA report — {project.name}",
                 run_id=body.run_id, status="queued")
    db.add(rep)
    db.flush()
    job = enqueue(db, "report", project_id=project.id, owner_id=user.id, payload={"report_id": rep.id})
    rep.job_id = job.id
    db.commit()
    return job


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, format: str = Query("pdf", pattern="^(pdf|html)$"),
                    project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rep = db.get(Report, report_id)
    if rep is None or rep.project_id != project.id:
        raise HTTPException(404, "Report not found")
    rel = rep.pdf_path if format == "pdf" else rep.html_path
    if rep.status != "ready" or not rel:
        raise HTTPException(409, f"Report is not ready (status: {rep.status})")
    p = (Path(settings.storage_root) / rel).resolve()
    if not str(p).startswith(str(Path(settings.storage_root).resolve())) or not p.exists():
        raise HTTPException(410, "Report file is no longer available (storage may have been reset); regenerate it")
    media = "application/pdf" if format == "pdf" else "text/html"
    return FileResponse(p, media_type=media, filename=f"testpilot-report-{rep.id}.{format}")
