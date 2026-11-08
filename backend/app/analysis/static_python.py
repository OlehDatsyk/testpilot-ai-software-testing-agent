"""Python static analysis: syntax validation, AST rules, complexity and Ruff.

The source is parsed with ``ast.parse`` — never imported or executed.
Every finding carries the exact source line it refers to as evidence.
"""
from __future__ import annotations

import ast
import builtins
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

BUILTIN_NAMES = {n for n in dir(builtins) if not n.startswith("_")} - {"copyright", "credits", "license", "exit", "quit"}
SECRET_NAMES = ("password", "passwd", "secret", "api_key", "apikey", "access_token", "private_key")


@dataclass
class RawFinding:
    rule_id: str
    file_path: str
    line: int | None
    column: int | None
    severity: str
    category: str
    title: str
    description: str
    suggestion: str | None
    method: str
    certainty: str = "potential"
    evidence: str | None = None
    extra: dict = field(default_factory=dict)


def source_line(lines: list[str], lineno: int | None) -> str | None:
    if lineno is None or lineno < 1 or lineno > len(lines):
        return None
    return lines[lineno - 1].rstrip()[:300]


def cyclomatic_complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.AsyncFor, ast.IfExp, ast.ExceptHandler, ast.With,
                              ast.AsyncWith, ast.Assert, ast.comprehension)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str]):
        self.rel = rel
        self.lines = lines
        self.findings: list[RawFinding] = []
        self.functions: list[dict] = []

    def add(self, node: ast.AST, rule: str, severity: str, category: str, title: str, desc: str,
            suggestion: str | None, certainty: str = "potential") -> None:
        line = getattr(node, "lineno", None)
        self.findings.append(RawFinding(rule, self.rel, line, getattr(node, "col_offset", None), severity, category,
                                        title, desc, suggestion, "python-ast", certainty, source_line(self.lines, line)))

    # --- functions -------------------------------------------------------------
    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        cc = cyclomatic_complexity(node)
        self.functions.append({"name": node.name, "line": node.lineno, "complexity": cc,
                               "length": (getattr(node, "end_lineno", node.lineno) - node.lineno + 1)})
        if cc > 10:
            self.add(node, "PY007", "low" if cc <= 15 else "medium", "complexity",
                     f"High cyclomatic complexity in '{node.name}' ({cc})",
                     f"Function '{node.name}' has an estimated cyclomatic complexity of {cc} (threshold 10). "
                     "Complex functions are harder to test exhaustively.",
                     "Split the function into smaller units and add tests for each branch.", "definite")
        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
        for d in defaults:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in ("list", "dict", "set")
            ):
                self.add(d, "PY002", "medium", "bug-risk", f"Mutable default argument in '{node.name}'",
                         "A mutable default value is created once and shared between calls, so state can leak "
                         "between invocations.",
                         "Use None as the default and create the object inside the function.", "definite")
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.arg in BUILTIN_NAMES:
                self.add(arg, "PY010", "low", "maintainability", f"Parameter '{arg.arg}' shadows a builtin",
                         f"The parameter name '{arg.arg}' hides the Python builtin of the same name inside "
                         f"'{node.name}'.", "Rename the parameter.", "definite")
        self.generic_visit(node)

    visit_FunctionDef = _check_function
    visit_AsyncFunctionDef = _check_function

    # --- exceptions ------------------------------------------------------------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.add(node, "PY001", "medium", "error-handling", "Bare 'except:' clause",
                     "A bare except also catches SystemExit and KeyboardInterrupt and can hide real errors.",
                     "Catch specific exception types, or at least 'except Exception:'.", "definite")
        elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
            if all(isinstance(s, ast.Pass) for s in node.body):
                self.add(node, "PY004", "medium", "error-handling", "Exception silently swallowed",
                         f"'except {node.type.id}: pass' discards every error without logging or handling it.",
                         "Handle the specific exception or log it before continuing.", "definite")
        self.generic_visit(node)

    # --- comparisons -----------------------------------------------------------
    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comp, ast.Constant) and comp.value is None:
                self.add(node, "PY003", "low", "style", "Comparison to None using ==/!=",
                         "Equality comparison with None can be overridden by __eq__; identity comparison is "
                         "the reliable form.", "Use 'is None' / 'is not None'.", "definite")
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(comp, ast.Constant) and isinstance(
                comp.value, (str, int, float, bytes)
            ) and not isinstance(comp.value, bool):
                self.add(node, "PY009", "medium", "bug-risk", "Identity comparison with a literal",
                         "'is' compares object identity; for literals the result depends on interpreter caching.",
                         "Use '==' to compare values.", "definite")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self.add(node, "PY005", "high", "bug", "Assertion on a non-empty tuple is always true",
                     "assert (cond, msg) asserts a tuple, which is always truthy, so the check never fails.",
                     "Write 'assert cond, msg' without parentheses.", "definite")
        self.generic_visit(node)

    # --- dangerous calls --------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
            self.add(node, "PY006", "high", "security", f"Use of {fn.id}()",
                     f"{fn.id}() executes arbitrary code. If any part of its input is user-controlled this is a "
                     "code-injection vulnerability.", "Use ast.literal_eval or explicit parsing instead.")
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                self.add(node, "PY011", "high", "security", "subprocess call with shell=True",
                         "Running commands through the shell enables command injection when arguments contain "
                         "untrusted input.", "Pass an argument list and keep shell=False.")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            right = node.right
            if isinstance(right, ast.Constant) and right.value == 0:
                self.add(node, "PY008", "high", "bug", "Division by literal zero",
                         "This expression always raises ZeroDivisionError.", "Remove or guard the division.",
                         "definite")
            elif isinstance(right, ast.Call) and isinstance(right.func, ast.Name) and right.func.id == "len":
                self.add(node, "PY012", "medium", "bug-risk", "Division by len() without visible empty check",
                         "Dividing by the length of a collection raises ZeroDivisionError when the collection is "
                         "empty. Verify that callers can never pass an empty collection.",
                         "Guard with 'if not items:' and return a defined value or raise a clear error.")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and len(node.value.value) >= 8:
            for t in node.targets:
                name = t.id if isinstance(t, ast.Name) else getattr(t, "attr", "")
                if name and any(s in name.lower() for s in SECRET_NAMES):
                    self.add(node, "PY013", "medium", "security", f"Possible hard-coded secret in '{name}'",
                             "A string literal is assigned to a credential-like name. Hard-coded secrets end up "
                             "in version control.", "Load the value from an environment variable or secret store.")
        self.generic_visit(node)


def analyse_python_file(root: Path, rel: str) -> tuple[list[RawFinding], dict]:
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], {"error": "not UTF-8"}
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [RawFinding("PY-SYNTAX", rel, exc.lineno, exc.offset, "high", "syntax", "Syntax error",
                           f"The file cannot be parsed by Python {sys.version_info.major}.{sys.version_info.minor}: "
                           f"{exc.msg}.", "Fix the syntax error; the module cannot be imported as written.",
                           "python-ast", "definite", source_line(lines, exc.lineno))], {"syntax_error": True}
    v = _Visitor(rel, lines)
    v.visit(tree)
    symbols = extract_symbols(tree)
    return v.findings, {"functions": v.functions, "symbols": symbols}


def extract_symbols(tree: ast.Module) -> list[dict]:
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out.append({"kind": "function", "name": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and not n.name.startswith("_")]
            out.append({"kind": "class", "name": node.name, "line": node.lineno, "methods": methods})
    return out


# --- Ruff ------------------------------------------------------------------------

RUFF_SELECT = "E7,E9,F,B"
RUFF_EQUIVALENT = {"E722": "PY001", "B006": "PY002", "E711": "PY003", "F631": "PY005", "F632": "PY009"}


def _ruff_severity(code: str) -> tuple[str, str]:
    if code.startswith("E9") or code in ("F821", "F822", "F823", "F811"):
        return "high", "bug"
    if code == "E722":
        return "medium", "error-handling"
    if code in ("F631", "F632"):
        return "high" if code == "F631" else "medium", "bug"
    if code.startswith("B"):
        return "medium", "bug-risk"
    if code in ("F401", "F841", "F541"):
        return "low", "maintainability"
    return "low", "style"


def ruff_binary() -> list[str] | None:
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    try:
        import ruff  # noqa: F401

        return [sys.executable, "-m", "ruff"]
    except ImportError:
        return None


def run_ruff(root: Path, files: list[str], file_lines: dict[str, list[str]]) -> tuple[list[RawFinding], dict]:
    """Run Ruff in isolated mode (ignores any config shipped inside the repository).

    Ruff is a static linter: it parses files and never executes them.
    """
    cmd = ruff_binary()
    if not cmd:
        return [], {"status": "unavailable", "reason": "ruff is not installed"}
    if not files:
        return [], {"status": "skipped", "reason": "no Python files"}
    args = cmd + ["check", "--isolated", "--no-cache", "--exit-zero", "--output-format", "json",
                  "--select", RUFF_SELECT, "--"] + files
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=120,
                              env={"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [], {"status": "error", "reason": type(exc).__name__}
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], {"status": "error", "reason": "unparseable ruff output"}
    out: list[RawFinding] = []
    for it in items:
        code = it.get("code") or "E999"
        fname = Path(it.get("filename", ""))
        try:
            rel = fname.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = fname.as_posix()
        line = (it.get("location") or {}).get("row")
        sev, cat = _ruff_severity(code)
        fix = (it.get("fix") or {}).get("message")
        out.append(RawFinding(f"RUFF-{code}", rel, line, (it.get("location") or {}).get("column"), sev, cat,
                              f"{code}: {it.get('message', '')[:200]}", it.get("message", ""),
                              fix or "See the Ruff rule documentation for the recommended fix.", "ruff", "definite",
                              source_line(file_lines.get(rel, []), line),
                              {"equivalent": RUFF_EQUIVALENT.get(code), "url": it.get("url")}))
    version = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    return out, {"status": "ran", "version": version, "rules": RUFF_SELECT, "findings": len(out)}
