"""Parsing of runner artefacts (JUnit XML, coverage JSON).

The artefacts are produced inside the sandbox from untrusted code, so they are
treated as untrusted input: size-capped, DOCTYPE/entity declarations rejected,
and every field truncated before storage.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

MAX_XML_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_TEXT = 20_000


class ArtefactError(ValueError):
    pass


@dataclass
class ParsedResult:
    node_id: str
    name: str
    classname: str | None
    file_path: str | None
    status: str
    duration: float | None
    message: str | None
    traceback: str | None


def _trunc(s: str | None, n: int = MAX_TEXT) -> str | None:
    if s is None:
        return None
    return s if len(s) <= n else s[:n] + f"\n… [truncated {len(s) - n} characters]"


def parse_junit(path: Path) -> list[ParsedResult]:
    if not path.exists():
        raise ArtefactError("junit.xml was not produced")
    data = path.read_bytes()
    if len(data) > MAX_XML_BYTES:
        raise ArtefactError("junit.xml exceeds size limit")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ArtefactError("junit.xml contains a DOCTYPE/ENTITY declaration and was rejected")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ArtefactError(f"junit.xml is malformed: {exc}") from exc
    results: list[ParsedResult] = []
    for case in root.iter("testcase"):
        name = case.get("name", "unnamed")[:300]
        classname = (case.get("classname") or "")[:300] or None
        file_path = case.get("file")
        if not file_path and classname:
            # pytest: "pkg.tests.test_x" -> "pkg/tests/test_x.py" ; vitest uses the file path as classname
            file_path = classname if "/" in classname or classname.endswith((".ts", ".js")) else classname.replace(".", "/") + ".py"
        try:
            duration = float(case.get("time", "0"))
        except ValueError:
            duration = None
        status, message, tb = "passed", None, None
        for tag, st in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            el = case.find(tag)
            if el is not None:
                status = st
                text = (el.text or "").strip()
                message = _trunc(el.get("message") or (text.splitlines()[0] if text else None), 2000)
                tb = _trunc(text) if st != "skipped" and text else None
                break
        node = f"{classname}::{name}" if classname else name
        results.append(ParsedResult(node[:500], name, classname, (file_path or "")[:500] or None, status, duration,
                                    message, tb))
    return results


def parse_python_coverage(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ArtefactError("coverage.json exceeds size limit")
    data = json.loads(path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    files = []
    for fname, info in (data.get("files") or {}).items():
        s = info.get("summary", {})
        files.append({
            "path": _rel(fname),
            "line_percent": round(float(s.get("percent_covered", 0.0)), 2),
            "statements": s.get("num_statements"),
            "covered": s.get("covered_lines"),
            "missing_lines": (info.get("missing_lines") or [])[:200],
            "branches": s.get("num_branches"),
            "covered_branches": s.get("covered_branches"),
        })
    nb, cb = totals.get("num_branches"), totals.get("covered_branches")
    return {
        "tool": f"coverage.py {data.get('meta', {}).get('version', '')}".strip(),
        "line_percent": _pct(totals.get("covered_lines"), totals.get("num_statements")),
        "branch_percent": _pct(cb, nb) if nb else None,
        "function_percent": None,  # coverage.py does not measure function coverage
        "lines_covered": totals.get("covered_lines"),
        "lines_total": totals.get("num_statements"),
        "files": sorted(files, key=lambda f: f["path"]),
    }


def parse_vitest_coverage(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ArtefactError("coverage-summary.json exceeds size limit")
    data = json.loads(path.read_text(encoding="utf-8"))
    total = data.get("total", {})
    files = []
    for fname, info in data.items():
        if fname == "total":
            continue
        files.append({
            "path": _rel(fname),
            "line_percent": info.get("lines", {}).get("pct"),
            "statements": info.get("lines", {}).get("total"),
            "covered": info.get("lines", {}).get("covered"),
            "branch_percent": info.get("branches", {}).get("pct"),
            "function_percent": info.get("functions", {}).get("pct"),
            "missing_lines": [],
        })
    return {
        "tool": "vitest (v8)",
        "line_percent": total.get("lines", {}).get("pct"),
        "branch_percent": total.get("branches", {}).get("pct"),
        "function_percent": total.get("functions", {}).get("pct"),
        "lines_covered": total.get("lines", {}).get("covered"),
        "lines_total": total.get("lines", {}).get("total"),
        "files": sorted(files, key=lambda f: f["path"]),
    }


def _pct(a, b) -> float | None:
    if not b:
        return None
    return round(100.0 * (a or 0) / b, 2)


def _rel(fname: str) -> str:
    f = fname.replace("\\", "/")
    for prefix in ("/work/",):
        if f.startswith(prefix):
            return f[len(prefix):]
    marker = "/work/"
    if marker in f:
        return f.split(marker, 1)[1]
    return f.rsplit("/work", 1)[-1].lstrip("/") if "/work" in f else f
