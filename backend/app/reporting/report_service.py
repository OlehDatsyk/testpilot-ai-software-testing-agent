"""QA report generation (HTML + PDF).

Reports separate three kinds of content and label each:
  * MEASURED   — static-analysis output, executed test results, measured coverage
  * SUGGESTED  — generated (unexecuted) test proposals, recommendations
  * LIMITATION — what was not analysed / not executed
No tokens, credentials or full source files are included.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BugReport, CoverageReport, Finding, GeneratedTest, Job, Project, Report, TestResult, TestRun
from app.services.analysis_service import latest_analysis
from app.services.jobs import log_activity

SEVERITIES = ["critical", "high", "medium", "low", "info"]


def collect_report_data(db: Session, project: Project, run_id: int | None) -> dict:
    analysis = latest_analysis(db, project.id)
    findings = []
    if analysis:
        findings = db.scalars(select(Finding).where(Finding.analysis_id == analysis.id)).all()
    open_findings = [f for f in findings if f.status in ("open", "accepted")]
    sev = Counter(f.severity for f in open_findings)
    gen_counts = dict(db.execute(select(GeneratedTest.status, func.count()).where(GeneratedTest.project_id == project.id)
                                 .group_by(GeneratedTest.status)).all())
    run = None
    if run_id:
        run = db.get(TestRun, run_id)
        if run and run.project_id != project.id:
            run = None
    if run is None:
        run = db.scalars(select(TestRun).where(TestRun.project_id == project.id, TestRun.total > 0)
                         .order_by(TestRun.id.desc()).limit(1)).first()
    failures, coverage = [], None
    if run:
        failures = db.scalars(select(TestResult).where(TestResult.run_id == run.id,
                                                       TestResult.status.in_(("failed", "error"))).limit(25)).all()
        coverage = db.scalars(select(CoverageReport).where(CoverageReport.run_id == run.id)).first()
    bugs = db.scalars(select(BugReport).where(BugReport.project_id == project.id).order_by(BugReport.id.desc()).limit(25)).all()
    summary = analysis.summary if analysis else {}
    gaps = summary.get("testing_gaps", [])

    recs = []
    if sev.get("critical") or sev.get("high"):
        recs.append(f"Review the {sev.get('critical', 0) + sev.get('high', 0)} open critical/high static-analysis findings.")
    if run and (run.failed or run.errors):
        recs.append(f"Investigate the {run.failed + run.errors} failing test(s) in run #{run.id} before release.")
    if gaps:
        recs.append(f"{len(gaps)} source module(s) have no test file referencing them (name-based heuristic).")
    if gen_counts.get("proposed"):
        recs.append(f"{gen_counts['proposed']} generated test proposal(s) are awaiting review.")
    if coverage and coverage.line_percent is not None and coverage.line_percent < 70:
        recs.append(f"Measured line coverage is {coverage.line_percent:.1f}%; prioritise untested modules.")
    if not run:
        recs.append("No test run with results exists yet; execution results are not part of this report.")

    limitations = [
        "Static analysis uses Python AST rules, Ruff, and heuristic JavaScript/TypeScript line rules. ESLint, tsc and mypy are not run.",
        "Generated tests are proposals until approved and executed; unexecuted tests are never counted as passed.",
        "Coverage shows which lines were executed, not whether the assertions were correct or sufficient.",
        "Third-party dependencies are not installed in the sandbox (network disabled); tests needing them fail to import.",
    ]
    if analysis:
        limitations.append(f"{analysis.files_skipped} file(s) were skipped (binary, oversized or excluded directories).")

    if run:
        verdict = (f"Run #{run.id} executed {run.total} test(s): {run.passed} passed, {run.failed} failed, "
                   f"{run.errors} errored, {run.skipped} skipped (status: {run.status}).")
    else:
        verdict = "No executed test results are available for this project."
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "project": project, "analysis": analysis, "summary": summary,
        "severity_counts": {s: sev.get(s, 0) for s in SEVERITIES},
        "top_findings": sorted(open_findings, key=lambda f: SEVERITIES.index(f.severity))[:20],
        "finding_total": len(findings), "gen_counts": gen_counts, "run": run, "failures": failures,
        "coverage": coverage, "bugs": bugs, "recommendations": recs, "limitations": limitations, "verdict": verdict,
        "gaps": gaps[:20],
    }


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{{ project.name }} — QA Report</title>
<style>
body{font-family:Inter,Segoe UI,Arial,sans-serif;color:#0f172a;margin:40px auto;max-width:960px;line-height:1.5;padding:0 16px}
h1{font-size:26px;margin:0}h2{font-size:18px;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin-top:32px}
.brand{color:#0891b2;font-weight:700;letter-spacing:.04em;font-size:13px;text-transform:uppercase}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:middle}
.measured{background:#dcfce7;color:#166534}.suggested{background:#fef3c7;color:#92400e}.limit{background:#e2e8f0;color:#334155}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #e2e8f0;text-align:left;padding:6px 8px;vertical-align:top}
th{background:#f8fafc}code,pre{font-family:ui-monospace,Consolas,monospace;font-size:12px}pre{background:#f1f5f9;padding:8px;overflow:auto;white-space:pre-wrap}
.kpis{display:flex;gap:12px;flex-wrap:wrap}.kpi{border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;min-width:120px}
.kpi b{display:block;font-size:20px}.muted{color:#64748b;font-size:13px}
</style></head><body>
<div class="brand">TestPilot AI · QA Report</div>
<h1>{{ project.name }}</h1>
<p class="muted">Generated {{ generated_at }}{% if project.is_demo %} · <b>DEMO PROJECT — not a real customer repository</b>{% endif %}</p>

<h2>Project</h2>
<table><tr><th>Repository</th><td>{{ project.repository_url or project.github_full_name or "Not connected (uploaded/manual)" }}</td></tr>
<tr><th>Snapshot</th><td>{% if summary.snapshot %}{{ summary.snapshot.source }} {{ summary.snapshot.ref or "" }} {{ (summary.snapshot.commit_sha or "")[:12] }}{% else %}none{% endif %}</td></tr>
<tr><th>Analysis date</th><td>{{ analysis.created_at.strftime("%Y-%m-%d %H:%M UTC") if analysis else "Not analysed" }}</td></tr>
<tr><th>Languages</th><td>{{ (summary.supported_languages or []) | join(", ") or "—" }}</td></tr>
<tr><th>Frameworks</th><td>{{ (summary.frameworks or []) | join(", ") or "—" }}</td></tr></table>

<h2>Final QA summary <span class="tag measured">MEASURED</span></h2>
<p>{{ verdict }}</p>

<h2>Static analysis <span class="tag measured">MEASURED</span></h2>
<div class="kpis">{% for s, c in severity_counts.items() %}<div class="kpi"><span class="muted">{{ s|capitalize }}</span><b>{{ c }}</b></div>{% endfor %}</div>
<p class="muted">Open and accepted findings from the latest analysis ({{ finding_total }} total including resolved / false positives). "Potential" findings need human review.</p>
{% if top_findings %}<table><tr><th>Severity</th><th>Location</th><th>Finding</th><th>Method</th><th>Certainty</th></tr>
{% for f in top_findings %}<tr><td>{{ f.severity }}</td><td><code>{{ f.file_path }}{% if f.line %}:{{ f.line }}{% endif %}</code></td><td>{{ f.title }}</td><td>{{ f.method }}</td><td>{{ f.certainty }}</td></tr>{% endfor %}</table>{% endif %}

<h2>Generated tests <span class="tag suggested">SUGGESTED</span></h2>
<p>Proposed: {{ gen_counts.get("proposed", 0) }} · Approved: {{ gen_counts.get("approved", 0) }} · Rejected: {{ gen_counts.get("rejected", 0) }}. Generated tests are not results; only executed tests below count.</p>

<h2>Execution results <span class="tag measured">MEASURED</span></h2>
{% if run %}<div class="kpis"><div class="kpi"><span class="muted">Total</span><b>{{ run.total }}</b></div><div class="kpi"><span class="muted">Passed</span><b>{{ run.passed }}</b></div><div class="kpi"><span class="muted">Failed</span><b>{{ run.failed }}</b></div><div class="kpi"><span class="muted">Errors</span><b>{{ run.errors }}</b></div><div class="kpi"><span class="muted">Skipped</span><b>{{ run.skipped }}</b></div></div>
<p class="muted">Run #{{ run.id }} · provider {{ run.provider }} · {{ run.language }} · {{ "%.2f"|format(run.duration_seconds or 0) }}s · status {{ run.status }}</p>
{% if failures %}<h3>Failed tests</h3>{% for r in failures %}<p><b>{{ r.name }}</b> <code>{{ r.file_path or "" }}</code><br>{{ r.message or "" }}</p>
{% if r.rule_analysis %}<p class="muted">Suggestion: {{ r.rule_analysis.meaning }}</p>{% endif %}{% endfor %}{% endif %}
{% else %}<p>No executed test run is available.</p>{% endif %}

<h2>Coverage <span class="tag measured">MEASURED</span></h2>
{% if coverage %}<p>Line coverage {{ "%.1f"|format(coverage.line_percent or 0) }}% ({{ coverage.lines_covered }}/{{ coverage.lines_total }} lines){% if coverage.branch_percent is not none %} · branch {{ "%.1f"|format(coverage.branch_percent) }}%{% endif %}{% if coverage.function_percent is not none %} · function {{ "%.1f"|format(coverage.function_percent) }}%{% endif %} — measured by {{ coverage.tool }}.</p>
<p class="muted">Coverage indicates which code was exercised, not whether the tests were correct or comprehensive.</p>
{% else %}<p>Coverage was not measured for this report.</p>{% endif %}

<h2>Bug reports</h2>
{% if bugs %}<table><tr><th>#</th><th>Title</th><th>Severity</th><th>Status</th><th>Location</th></tr>{% for b in bugs %}<tr><td>{{ b.id }}</td><td>{{ b.title }}</td><td>{{ b.severity }}</td><td>{{ b.status }}</td><td><code>{{ b.file_path or "" }}{% if b.line %}:{{ b.line }}{% endif %}</code></td></tr>{% endfor %}</table>{% else %}<p>No bug reports.</p>{% endif %}

<h2>Recommendations <span class="tag suggested">SUGGESTED</span></h2>
<ul>{% for r in recommendations %}<li>{{ r }}</li>{% endfor %}</ul>
{% if gaps %}<p class="muted">Modules without a referencing test file (heuristic):</p><ul>{% for g in gaps %}<li><code>{{ g.file }}</code></li>{% endfor %}</ul>{% endif %}

<h2>Known limitations <span class="tag limit">LIMITATION</span></h2>
<ul>{% for l in limitations %}<li>{{ l }}</li>{% endfor %}</ul>
<p class="muted">Pass rate is not a measure of overall software quality.</p>
</body></html>"""

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_template = _env.from_string(HTML)


def render_html(data: dict) -> str:
    return _template.render(**data)


def render_pdf(data: dict, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as esc

    styles = getSampleStyleSheet()
    brand = ParagraphStyle("brand", parent=styles["Normal"], textColor=colors.HexColor("#0891b2"), fontSize=9)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#475569"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13)
    story = [Paragraph("TESTPILOT AI · QA REPORT", brand), Paragraph(esc(data["project"].name), styles["Title"])]
    meta = f"Generated {data['generated_at']}"
    if data["project"].is_demo:
        meta += " · DEMO PROJECT — not a real customer repository"
    story += [Paragraph(esc(meta), small), Spacer(1, 6 * mm)]

    def h(text, tag=None):
        story.append(Paragraph(esc(text) + (f" <font color='#92400e' size='8'>[{tag}]</font>" if tag else ""), styles["Heading2"]))

    def table(rows, widths=None):
        t = Table([[Paragraph(esc(str(c)), small) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)

    s = data["summary"]
    h("Project")
    table([["Field", "Value"],
           ["Repository", data["project"].repository_url or data["project"].github_full_name or "Not connected"],
           ["Languages", ", ".join(s.get("supported_languages", [])) or "—"],
           ["Frameworks", ", ".join(s.get("frameworks", [])) or "—"],
           ["Analysis date", data["analysis"].created_at.strftime("%Y-%m-%d %H:%M UTC") if data["analysis"] else "Not analysed"]],
          [40 * mm, 130 * mm])
    h("Final QA summary", "MEASURED")
    story.append(Paragraph(esc(data["verdict"]), body))
    h("Static analysis", "MEASURED")
    table([["Severity", "Open findings"]] + [[k, v] for k, v in data["severity_counts"].items()], [40 * mm, 40 * mm])
    if data["top_findings"]:
        story.append(Spacer(1, 3 * mm))
        table([["Severity", "Location", "Finding", "Certainty"]] +
              [[f.severity, f"{f.file_path}:{f.line or ''}", f.title, f.certainty] for f in data["top_findings"]],
              [20 * mm, 55 * mm, 75 * mm, 20 * mm])
    h("Generated tests", "SUGGESTED")
    g = data["gen_counts"]
    story.append(Paragraph(esc(f"Proposed {g.get('proposed', 0)} · Approved {g.get('approved', 0)} · Rejected "
                               f"{g.get('rejected', 0)}. Proposals are not results."), body))
    h("Execution results", "MEASURED")
    run = data["run"]
    if run:
        table([["Run", "Status", "Total", "Passed", "Failed", "Errors", "Skipped", "Duration"],
               [f"#{run.id}", run.status, run.total, run.passed, run.failed, run.errors, run.skipped,
                f"{run.duration_seconds or 0:.2f}s"]])
        for r in data["failures"]:
            story.append(Paragraph(f"<b>{esc(r.name)}</b> — {esc((r.message or '')[:300])}", small))
    else:
        story.append(Paragraph("No executed test run is available.", body))
    h("Coverage", "MEASURED")
    c = data["coverage"]
    if c:
        story.append(Paragraph(esc(f"Line {c.line_percent or 0:.1f}% ({c.lines_covered}/{c.lines_total})"
                                   + (f", branch {c.branch_percent:.1f}%" if c.branch_percent is not None else "")
                                   + f" — {c.tool}. Coverage shows exercised code, not test correctness."), body))
    else:
        story.append(Paragraph("Coverage was not measured.", body))
    h("Bug reports")
    if data["bugs"]:
        table([["#", "Title", "Severity", "Status"]] + [[b.id, b.title, b.severity, b.status] for b in data["bugs"]],
              [12 * mm, 110 * mm, 25 * mm, 25 * mm])
    else:
        story.append(Paragraph("No bug reports.", body))
    h("Recommendations", "SUGGESTED")
    for r in data["recommendations"]:
        story.append(Paragraph("• " + esc(r), body))
    h("Known limitations", "LIMITATION")
    for lim in data["limitations"]:
        story.append(Paragraph("• " + esc(lim), body))
    SimpleDocTemplate(str(path), pagesize=A4, title=f"{data['project'].name} QA Report", author="TestPilot AI",
                      leftMargin=18 * mm, rightMargin=18 * mm).build(story)


def handle_report(db: Session, job: Job) -> dict:
    report = db.get(Report, job.payload["report_id"])
    project = db.get(Project, job.project_id)
    data = collect_report_data(db, project, report.run_id)
    out_dir = Path(settings.storage_root) / "reports" / str(project.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path, pdf_path = out_dir / f"report_{report.id}.html", out_dir / f"report_{report.id}.pdf"
    html_path.write_text(render_html(data), encoding="utf-8")
    render_pdf(data, pdf_path)
    base = Path(settings.storage_root)
    report.html_path = html_path.relative_to(base).as_posix()
    report.pdf_path = pdf_path.relative_to(base).as_posix()
    report.status = "ready"
    report.run_id = data["run"].id if data["run"] else None
    report.summary = {"severity_counts": data["severity_counts"], "verdict": data["verdict"],
                      "recommendations": data["recommendations"]}
    log_activity(db, project, job.owner_id, "report.generated", report.title)
    db.commit()
    return {"report_id": report.id}
