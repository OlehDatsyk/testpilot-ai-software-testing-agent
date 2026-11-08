"""Test generation job: rule-based proposals plus optional AI proposals."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import AIUnavailable, get_provider
from app.analysis.repository import read_text
from app.generators import js_tests, python_tests
from app.generators.ai_tests import generate_with_ai
from app.models import GeneratedTest, Job, Project, RepositorySnapshot
from app.services.analysis_service import latest_analysis
from app.services.jobs import log_activity
from app.services.snapshots import snapshot_root

log = logging.getLogger(__name__)
MAX_FILES = 60
MAX_AI_FILES = 5


def handle_generation(db: Session, job: Job) -> dict:
    project = db.get(Project, job.project_id)
    snap = db.get(RepositorySnapshot, project.latest_snapshot_id) if project and project.latest_snapshot_id else None
    analysis = latest_analysis(db, project.id) if project else None
    if not project or not snap or not analysis:
        raise ValueError("Run repository analysis before generating tests")
    root = snapshot_root(snap)
    summary = analysis.summary
    requested = set(job.payload.get("files") or [])
    use_ai = bool(job.payload.get("use_ai"))
    focus = job.payload.get("focus")

    candidates = list(summary.get("symbols", {}).keys())
    if requested:
        candidates = [c for c in candidates if c in requested]
    # Prioritise files flagged as testing gaps
    gap_files = {g["file"] for g in summary.get("testing_gaps", [])}
    candidates.sort(key=lambda p: (p not in gap_files, p))
    candidates = candidates[:MAX_FILES]

    existing = {(t.name, t.target_file) for t in db.scalars(
        select(GeneratedTest).where(GeneratedTest.project_id == project.id, GeneratedTest.status != "rejected"))}

    created, ai_used, ai_errors = 0, 0, []
    provider = get_provider()
    for rel in candidates:
        source = read_text(root, rel)
        if source is None:
            continue
        lang = "Python" if rel.endswith(".py") else ("TypeScript" if rel.endswith((".ts", ".tsx", ".mts")) else "JavaScript")
        if lang == "Python":
            proposals = python_tests.generate_for_file(rel, source)
        else:
            proposals = js_tests.generate_for_file(rel, source)
        generator = "rule-based"
        if use_ai and ai_used < MAX_AI_FILES:
            if provider.available:
                try:
                    proposals += generate_with_ai(provider, rel, source, lang, summary.get("test_files", []), focus)
                    ai_used += 1
                except AIUnavailable as exc:
                    ai_errors.append(f"{rel}: {exc}")
            elif not ai_errors:
                ai_errors.append("AI provider not configured; only rule-based tests were generated")
        for p in proposals:
            if (p.name, p.target_file) in existing:
                continue
            existing.add((p.name, p.target_file))
            validation = (python_tests.validate_python_test(p.code) if lang == "Python" else js_tests.validate_js_test(p.code))
            validation["strategy"] = p.strategy
            db.add(GeneratedTest(
                project_id=project.id, snapshot_id=snap.id, job_id=job.id, name=p.name, description=p.description,
                target=p.target, target_file=p.target_file, category=p.category, language=lang,
                framework="pytest" if lang == "Python" else "vitest", expected_behaviour=p.expected_behaviour,
                code=p.code, rationale=p.rationale, source_files=p.source_files,
                generator=(provider.label if p.strategy == "ai" else generator), status="proposed",
                validation=validation))
            created += 1
    log_activity(db, project, job.owner_id, "tests.generated", f"{created} test proposals created")
    db.commit()
    return {"created": created, "files_considered": len(candidates), "ai_files": ai_used, "ai_messages": ai_errors[:10]}
