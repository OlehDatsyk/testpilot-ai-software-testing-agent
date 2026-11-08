"""Repository + static analysis job."""
from __future__ import annotations

import hashlib
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.repository import analyse_structure, read_text, scan_repository
from app.analysis.static_js import analyse_js_file
from app.analysis.static_python import RawFinding, analyse_python_file, run_ruff
from app.core.config import settings
from app.models import Finding, Job, Project, RepositoryAnalysis, RepositorySnapshot
from app.services.jobs import log_activity
from app.services.snapshots import snapshot_root

MAX_ANALYSED_FILES = 1500


def fingerprint(f: RawFinding) -> str:
    raw = f"{f.rule_id}|{f.file_path}|{(f.evidence or '').strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def handle_analysis(db: Session, job: Job) -> dict:
    project = db.get(Project, job.project_id)
    snap = db.get(RepositorySnapshot, job.payload["snapshot_id"])
    if project is None or snap is None or snap.project_id != project.id:
        raise ValueError("Project or snapshot not found")
    started = time.monotonic()
    root = snapshot_root(snap)
    scan = scan_repository(root, settings.max_file_size_kb * 1024)
    summary = analyse_structure(root, scan)

    raw: list[RawFinding] = []
    symbols: dict[str, list] = {}
    complexity: list[dict] = []
    py_files, js_files = [], []
    inspected = 0
    for f in scan.files:
        if not f.parsed or inspected >= MAX_ANALYSED_FILES:
            continue
        if f.language == "Python":
            findings, meta = analyse_python_file(root, f.path)
            py_files.append(f.path)
        elif f.language in ("JavaScript", "TypeScript"):
            findings, meta = analyse_js_file(root, f.path)
            js_files.append(f.path)
        else:
            continue
        inspected += 1
        raw.extend(findings)
        if not f.is_test and meta.get("symbols"):
            symbols[f.path] = meta["symbols"]
        if not f.is_test:
            for fn in meta.get("functions", []):
                complexity.append({"file": f.path, **fn})

    file_lines = {p: (read_text(root, p) or "").splitlines() for p in py_files}
    ruff_findings, ruff_meta = run_ruff(root, py_files, file_lines)
    # De-duplicate: if Ruff reports the equivalent of an AST rule on the same line, keep Ruff's (tool-backed).
    ruff_keys = {(r.extra.get("equivalent"), r.file_path, r.line) for r in ruff_findings if r.extra.get("equivalent")}
    raw = [r for r in raw if (r.rule_id, r.file_path, r.line) not in ruff_keys] + ruff_findings

    # Carry review decisions forward (false positives stay false positives across re-analysis).
    previous = {fp: st for fp, st in db.execute(
        select(Finding.fingerprint, Finding.status).where(Finding.project_id == project.id)).all()}

    analysis = RepositoryAnalysis(
        project_id=project.id, snapshot_id=snap.id, job_id=job.id,
        files_inspected=inspected, files_skipped=len(scan.skipped),
        tools={
            "python-ast": {"status": "ran" if py_files else "skipped", "files": len(py_files)},
            "ruff": ruff_meta,
            "js-rules": {"status": "ran" if js_files else "skipped", "files": len(js_files),
                         "note": "Heuristic line rules; not a full parser"},
            "eslint": {"status": "not_implemented", "reason": "ESLint integration is on the roadmap"},
            "tsc": {"status": "not_implemented", "reason": "TypeScript compiler checks are on the roadmap"},
            "mypy": {"status": "not_implemented", "reason": "mypy integration is on the roadmap"},
        },
    )
    summary["symbols"] = {k: v for k, v in list(symbols.items())[:300]}
    summary["complexity_top"] = sorted(complexity, key=lambda c: -c["complexity"])[:20]
    summary["snapshot"] = {"id": snap.id, "source": snap.source, "ref": snap.ref, "commit_sha": snap.commit_sha}
    analysis.summary = summary
    db.add(analysis)
    db.flush()

    seen = set()
    for r in raw:
        fp = fingerprint(r)
        if fp in seen:
            continue
        seen.add(fp)
        db.add(Finding(
            project_id=project.id, analysis_id=analysis.id, rule_id=r.rule_id, file_path=r.file_path, line=r.line,
            column=r.column, severity=r.severity, category=r.category, title=r.title[:300], description=r.description,
            evidence=r.evidence, suggestion=r.suggestion, method=r.method, certainty=r.certainty,
            status=previous.get(fp, "open"), fingerprint=fp,
        ))
    analysis.duration_ms = int((time.monotonic() - started) * 1000)
    project.languages = summary["supported_languages"]
    project.frameworks = summary["frameworks"]
    project.status = "ready"
    log_activity(db, project, job.owner_id, "analysis.completed",
                 f"{inspected} files analysed, {len(seen)} findings")
    db.commit()
    return {"analysis_id": analysis.id, "findings": len(seen), "files_inspected": inspected}


def latest_analysis(db: Session, project_id: int) -> RepositoryAnalysis | None:
    return db.scalars(select(RepositoryAnalysis).where(RepositoryAnalysis.project_id == project_id)
                      .order_by(RepositoryAnalysis.id.desc()).limit(1)).first()
