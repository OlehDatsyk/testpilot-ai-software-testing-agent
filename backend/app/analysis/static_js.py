"""JavaScript / TypeScript rule-based static checks.

This is a lightweight, dependency-free analyser: comments and string literals
are blanked out (preserving line numbers) and a set of conservative rules is
applied line by line. It is not a full parser — findings are labelled with the
method ``js-rules`` and documented as heuristic. ESLint / tsc integration is a
documented roadmap item.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.analysis.static_python import RawFinding, source_line


def strip_comments_and_strings(src: str) -> str:
    out = []
    i, n = 0, len(src)
    state = None  # None | "line" | "block" | quote char
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"; out.append("  "); i += 2; continue
            if c == "/" and nxt == "*":
                state = "block"; out.append("  "); i += 2; continue
            if c in ("'", '"', "`"):
                state = c; out.append(c); i += 1; continue
            out.append(c); i += 1
        elif state == "line":
            if c == "\n":
                state = None; out.append("\n")
            else:
                out.append(" ")
            i += 1
        elif state == "block":
            if c == "*" and nxt == "/":
                state = None; out.append("  "); i += 2; continue
            out.append("\n" if c == "\n" else " "); i += 1
        else:  # inside a string literal
            if c == "\\":
                out.append("  " if nxt != "\n" else " \n"); i += 2; continue
            if c == state:
                state = None; out.append(c); i += 1; continue
            out.append("\n" if c == "\n" else " "); i += 1
    return "".join(out)


RULES: list[tuple[str, re.Pattern[str], str, str, str, str, str, str, bool]] = [
    # id, pattern, severity, category, title, description, suggestion, certainty, ts_only
    ("JS001", re.compile(r"[^=!<>]([!=])=(?!=)\s*(?!null\b|undefined\b)"), "low", "bug-risk", "Loose equality operator",
     "'==' / '!=' perform type coercion, which can produce surprising results (e.g. '0' == 0).",
     "Use '===' / '!=='.", "definite", False),
    ("JS002", re.compile(r"\beval\s*\(|\bnew\s+Function\s*\("), "high", "security", "Dynamic code evaluation",
     "eval / new Function execute strings as code; with untrusted input this is a code-injection risk.",
     "Replace with explicit parsing (e.g. JSON.parse) or a lookup table.", "potential", False),
    ("JS003", re.compile(r"^\s*debugger\s*;?\s*$"), "medium", "maintainability", "debugger statement",
     "A debugger statement pauses execution when developer tools are open and should not ship.",
     "Remove the debugger statement.", "definite", False),
    ("JS004", re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}"), "medium", "error-handling", "Empty catch block",
     "Errors caught here are silently discarded.", "Handle, log or rethrow the error.", "definite", False),
    ("JS005", re.compile(r"(^|[;{}\s])var\s+[A-Za-z_$]"), "info", "style", "'var' declaration",
     "'var' is function-scoped and hoisted, which can cause subtle bugs.", "Use 'let' or 'const'.", "definite", False),
    ("JS006", re.compile(r"\bconsole\.log\s*\("), "info", "maintainability", "console.log in source",
     "Debug logging left in production code.", "Remove it or use a logger with levels.", "definite", False),
    ("JS007", re.compile(r":\s*any\b|<any>|\bas\s+any\b"), "low", "type-safety", "Explicit 'any' type",
     "'any' disables type checking for this value.", "Use a precise type or 'unknown'.", "definite", True),
    ("JS008", re.compile(r"\.innerHTML\s*=|dangerouslySetInnerHTML"), "medium", "security", "Raw HTML injection",
     "Assigning HTML strings can introduce cross-site scripting if any part is user-controlled.",
     "Use textContent or sanitise the HTML.", "potential", False),
    ("JS009", re.compile(r"\bparseInt\s*\(\s*[^,()]+\)"), "low", "bug-risk", "parseInt without radix",
     "Without an explicit radix, parsing behaviour can differ for some inputs.", "Pass 10 as the second argument.",
     "definite", False),
]


def analyse_js_file(root: Path, rel: str) -> tuple[list[RawFinding], dict]:
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], {"error": "not UTF-8"}
    original = text.splitlines()
    stripped = strip_comments_and_strings(text).splitlines()
    is_ts = rel.endswith((".ts", ".tsx", ".mts", ".cts"))
    findings: list[RawFinding] = []
    for idx, line in enumerate(stripped, start=1):
        for rid, pat, sev, cat, title, desc, sugg, certainty, ts_only in RULES:
            if ts_only and not is_ts:
                continue
            m = pat.search(line)
            if m:
                findings.append(RawFinding(rid, rel, idx, m.start() + 1, sev, cat, title, desc, sugg, "js-rules",
                                           certainty, source_line(original, idx)))
    # Brace balance as a coarse syntax sanity check
    opens, closes = sum(s.count("{") for s in stripped), sum(s.count("}") for s in stripped)
    if opens != closes:
        findings.append(RawFinding("JS-BRACES", rel, None, None, "medium", "syntax", "Unbalanced braces",
                                   f"Found {opens} '{{' and {closes} '}}' outside strings/comments. The file may not "
                                   "parse.", "Check the file with the TypeScript compiler or Node.", "js-rules",
                                   "potential", None))
    return findings, {"symbols": extract_js_exports("\n".join(stripped))}


EXPORT_FN = re.compile(r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)")
EXPORT_CONST_FN = re.compile(r"export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?\(([^)]*)\)\s*(?::[^=]+)?=>")
EXPORT_CLASS = re.compile(r"export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")


def extract_js_exports(stripped: str) -> list[dict]:
    out = []
    for m in EXPORT_FN.finditer(stripped):
        out.append({"kind": "function", "name": m.group(1), "params": _params(m.group(2))})
    for m in EXPORT_CONST_FN.finditer(stripped):
        out.append({"kind": "function", "name": m.group(1), "params": _params(m.group(2))})
    for m in EXPORT_CLASS.finditer(stripped):
        out.append({"kind": "class", "name": m.group(1)})
    return out


def _params(raw: str) -> list[str]:
    names = []
    for p in raw.split(","):
        p = p.strip()
        if not p:
            continue
        p = re.split(r"[:=?]", p, maxsplit=1)[0].strip().lstrip(".")
        names.append(p)
    return names
