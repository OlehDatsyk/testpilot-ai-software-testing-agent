"""AI Testing Assistant.

Answers are grounded in stored project data only. With an AI provider the
model receives a compact JSON context and must answer from it; without one a
deterministic responder answers the common questions directly from the
database. In both cases, missing information is stated, never invented.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import AIUnavailable, get_provider
from app.ai.schemas import AIAssistantAnswer, AIFailureAnalysis
from app.models import CoverageReport, Finding, GeneratedTest, Project, TestResult, TestRun
from app.services.analysis_service import latest_analysis

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def build_context(db: Session, project: Project) -> dict:
    ctx: dict = {"project": {"name": project.name, "is_demo": project.is_demo, "languages": project.languages,
                             "frameworks": project.frameworks}}
    analysis = latest_analysis(db, project.id)
    if analysis:
        s = analysis.summary
        ctx["analysis"] = {
            "date": analysis.created_at.isoformat(), "totals": s.get("totals"), "frameworks": s.get("frameworks"),
            "test_frameworks": s.get("test_frameworks"), "source_directories": s.get("source_directories", [])[:20],
            "test_directories": s.get("test_directories", [])[:20], "config_files": s.get("config_files", [])[:30],
            "testing_gaps": s.get("testing_gaps", [])[:25], "complexity_top": s.get("complexity_top", [])[:10],
            "symbols": {k: [x["name"] for x in v][:20] for k, v in list(s.get("symbols", {}).items())[:40]},
        }
        findings = db.scalars(select(Finding).where(Finding.analysis_id == analysis.id,
                                                    Finding.status.in_(("open", "accepted")))).all()
        findings = sorted(findings, key=lambda f: SEV_ORDER.get(f.severity, 9))
        ctx["open_findings"] = [{"id": f.id, "severity": f.severity, "file": f.file_path, "line": f.line,
                                 "title": f.title, "certainty": f.certainty, "method": f.method} for f in findings[:30]]
    run = db.scalars(select(TestRun).where(TestRun.project_id == project.id).order_by(TestRun.id.desc()).limit(1)).first()
    if run:
        ctx["latest_run"] = {"id": run.id, "status": run.status, "total": run.total, "passed": run.passed,
                             "failed": run.failed, "errors": run.errors, "skipped": run.skipped,
                             "duration_seconds": run.duration_seconds, "provider": run.provider,
                             "error_message": run.error_message}
        fails = db.scalars(select(TestResult).where(TestResult.run_id == run.id,
                                                    TestResult.status.in_(("failed", "error"))).limit(15)).all()
        ctx["latest_failures"] = [{"result_id": r.id, "name": r.name, "file": r.file_path, "message": (r.message or "")[:400],
                                   "traceback_tail": (r.traceback or "")[-800:],
                                   "exception": (r.rule_analysis or {}).get("exception_type")} for r in fails]
        cov = db.scalars(select(CoverageReport).where(CoverageReport.run_id == run.id)).first()
        if cov:
            ctx["coverage"] = {"line_percent": cov.line_percent, "branch_percent": cov.branch_percent,
                               "function_percent": cov.function_percent, "tool": cov.tool,
                               "lowest_files": sorted(cov.files, key=lambda f: f.get("line_percent") or 0)[:10]}
    gen = db.scalars(select(GeneratedTest).where(GeneratedTest.project_id == project.id)).all()
    ctx["generated_tests"] = {"proposed": sum(t.status == "proposed" for t in gen),
                              "approved": sum(t.status == "approved" for t in gen),
                              "rejected": sum(t.status == "rejected" for t in gen)}
    return ctx


SYSTEM = (
    "You are the TestPilot testing assistant. Answer ONLY from the JSON context provided. Never invent files, "
    "test results, coverage values, error messages, code locations or history. If the context lacks the needed "
    "information, say exactly what is missing and how the user can produce it (e.g. run analysis, execute tests). "
    "Distinguish measured results from suggestions. Be concise; use Markdown."
)


def answer(db: Session, project: Project, question: str, history: list[dict]) -> tuple[str, str, list[str]]:
    ctx = build_context(db, project)
    provider = get_provider()
    if provider.available:
        convo = "\n".join(f"{m['role']}: {m['content'][:1500]}" for m in history[-6:])
        prompt = f"<context>\n{json.dumps(ctx, default=str)[:60000]}\n</context>\n\n<conversation>\n{convo}\n</conversation>\n\nQuestion: {question}"
        try:
            res = provider.structured(system=SYSTEM, prompt=prompt, schema=AIAssistantAnswer, max_tokens=4000)
            return res.answer, provider.label, res.used_sources[:10]
        except AIUnavailable as exc:
            text, sources = grounded_answer(ctx, question)
            return f"_AI provider unavailable ({exc}); answered from stored data instead._\n\n{text}", "grounded-rules", sources
    text, sources = grounded_answer(ctx, question)
    return text, "grounded-rules", sources


def grounded_answer(ctx: dict, q: str) -> tuple[str, list[str]]:
    ql = q.lower()
    a, run = ctx.get("analysis"), ctx.get("latest_run")
    no_analysis = "No repository analysis exists yet. Run **Repository Analysis** first."
    no_run = "No test run has been executed for this project yet, so there are no results to report."

    if any(k in ql for k in ("stack trace", "why", "fail", "error")):
        fails = ctx.get("latest_failures") or []
        if not run:
            return no_run, []
        if not fails:
            return f"The latest run (#{run['id']}, status `{run['status']}`) has no failed or errored tests.", ["latest_run"]
        lines = [f"Latest run #{run['id']}: **{run['failed']} failed, {run['errors']} errors** of {run['total']} executed.\n"]
        for f in fails[:8]:
            first = (f["message"] or "").strip().splitlines()[0][:200] if f["message"] else ""
            lines.append(f"- `{f['name']}` (`{f['file'] or 'unknown file'}`): {f['exception'] or 'failure'} — {first}")
        lines.append("\nOpen a result on the **Test Runs** page for the full traceback and the rule-based explanation. "
                     "Explanations are suggestions; the raw output is authoritative.")
        return "\n".join(lines), ["latest_run", "latest_failures"]
    if "coverage" in ql or "uncovered" in ql or "no test" in ql:
        parts, src = [], []
        cov = ctx.get("coverage")
        if cov:
            parts.append(f"Measured line coverage in run #{run['id']}: **{cov['line_percent']}%** ({cov['tool']}).")
            low = [f for f in cov["lowest_files"] if (f.get("line_percent") or 0) < 100][:8]
            if low:
                parts.append("Lowest-covered files:\n" + "\n".join(f"- `{f['path']}` — {f['line_percent']}%" for f in low))
            src.append("coverage")
        else:
            parts.append("Coverage has not been measured (no executed run with coverage data).")
        if a and a.get("testing_gaps"):
            parts.append("Modules with no test file referencing them (name-based heuristic):\n"
                         + "\n".join(f"- `{g['file']}`" for g in a["testing_gaps"][:10]))
            src.append("analysis.testing_gaps")
        return "\n\n".join(parts), src
    if any(k in ql for k in ("architecture", "structure", "explain the project", "overview")):
        if not a:
            return no_analysis, []
        t = a["totals"] or {}
        txt = (f"**{ctx['project']['name']}** — languages: {', '.join(ctx['project']['languages']) or 'none detected'}; "
               f"frameworks: {', '.join(a['frameworks'] or []) or 'none detected'}.\n\n"
               f"- {t.get('supported_source_files', 0)} supported source files, {t.get('test_files', 0)} test files\n"
               f"- Source directories: {', '.join(a['source_directories'][:8]) or '—'}\n"
               f"- Test directories: {', '.join(a['test_directories'][:8]) or '—'}\n"
               f"- Test frameworks: {', '.join(a['test_frameworks'] or []) or 'none detected'}\n\n"
               "Public symbols per file:\n" + "\n".join(f"- `{k}`: {', '.join(v[:8])}" for k, v in list(a["symbols"].items())[:12]))
        return txt, ["analysis"]
    if any(k in ql for k in ("which functions", "more tests", "complex", "what should i test", "priorit")) and "release" not in ql:
        if not a:
            return no_analysis, []
        lines = ["Prioritised from stored analysis data:"]
        for c in a.get("complexity_top", [])[:6]:
            lines.append(f"- `{c['file']}::{c['name']}` — cyclomatic complexity {c['complexity']}")
        for g in a.get("testing_gaps", [])[:6]:
            lines.append(f"- `{g['file']}` — {g['reason']}")
        for f in (ctx.get("open_findings") or [])[:5]:
            lines.append(f"- `{f['file']}:{f['line']}` — {f['severity']} finding: {f['title']}")
        return "\n".join(lines) if len(lines) > 1 else "No complexity hot spots, gaps or findings are recorded.", ["analysis", "open_findings"]
    if any(k in ql for k in ("release", "qa summary", "summar", "status")):
        parts = []
        if run:
            parts.append(f"**Latest run #{run['id']}** (`{run['status']}`): {run['passed']} passed, {run['failed']} failed, "
                         f"{run['errors']} errors, {run['skipped']} skipped.")
        else:
            parts.append(no_run)
        of = ctx.get("open_findings")
        if of is not None:
            hi = [f for f in of if f["severity"] in ("critical", "high")]
            parts.append(f"Open static findings: {len(of)} ({len(hi)} critical/high).")
        g = ctx["generated_tests"]
        parts.append(f"Generated tests: {g['proposed']} awaiting review, {g['approved']} approved.")
        if ctx.get("coverage"):
            parts.append(f"Measured line coverage: {ctx['coverage']['line_percent']}%.")
        if "release" in ql:
            parts.append("\n**Before releasing (derived from the data above):**\n"
                         + "\n".join(x for x in [
                             "- Resolve or triage failing tests" if run and (run["failed"] or run["errors"]) else "",
                             "- Review critical/high findings" if of and any(f["severity"] in ("critical", "high") for f in of) else "",
                             "- Review pending generated tests" if g["proposed"] else "",
                             "- Add tests for modules listed as testing gaps" if a and a.get("testing_gaps") else "",
                         ] if x) or "- No blocking items recorded.")
        return "\n\n".join(parts), ["latest_run", "open_findings", "generated_tests"]
    if any(k in ql for k in ("finding", "bug", "issue", "problem")):
        of = ctx.get("open_findings")
        if of is None:
            return no_analysis, []
        if not of:
            return "There are no open static-analysis findings.", ["open_findings"]
        return ("Open findings (static analysis; *potential* ones need review):\n"
                + "\n".join(f"- **{f['severity']}** `{f['file']}:{f['line']}` {f['title']} ({f['certainty']}, {f['method']})"
                            for f in of[:12])), ["open_findings"]
    if "generate" in ql and "test" in ql:
        return ("Use **Test Generation** to create proposals for this project. Without an AI provider, TestPilot "
                "generates rule-based tests from docstring examples, explicit `raise` guards and edge inputs. "
                f"Currently {ctx['generated_tests']['proposed']} proposals await review."), ["generated_tests"]
    return ("I can answer from this project's stored data: architecture/structure, which functions need tests, "
            "latest run summary, failures and stack traces, coverage, open findings and a release checklist. "
            "No AI provider is configured, so free-form questions outside these topics cannot be answered."), []


FAIL_SYSTEM = (
    "You analyse a failed automated test. Use ONLY the supplied test output and source excerpt. Do not invent "
    "files or line numbers that are not present in the output. This is a suggestion that a human will verify."
)


def ai_failure_analysis(db: Session, result: TestResult, source_excerpt: str | None) -> dict:
    provider = get_provider()
    if not provider.available:
        raise AIUnavailable("No AI provider is configured; the rule-based analysis is shown instead")
    prompt = (f"Test: {result.name}\nFile: {result.file_path}\nStatus: {result.status}\n"
              f"Message:\n{(result.message or '')[:2000]}\n\nTraceback:\n{(result.traceback or '')[-6000:]}\n"
              + (f"\nSource excerpt:\n{source_excerpt[:6000]}" if source_excerpt else ""))
    res = provider.structured(system=FAIL_SYSTEM, prompt=prompt, schema=AIFailureAnalysis, max_tokens=3000)
    data = res.model_dump()
    data["kind"] = "ai-suggestion"
    data["provider"] = provider.label
    return data
