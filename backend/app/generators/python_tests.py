"""Rule-based pytest generation from Python source (AST only, nothing is executed).

Strategies, each grounded in something visible in the source:

* ``import``          – the module can be imported (baseline smoke test)
* ``doctest``         – examples written in the function docstring become assertions
* ``guard``           – ``if <param condition>: raise X`` becomes a pytest.raises test
* ``edge``            – heuristic edge inputs (empty list, zero, empty string). The
                        expectation is explicitly a *heuristic*: "returns, or raises
                        an exception the function itself raises". These must be
                        reviewed before approval.
"""
from __future__ import annotations

import ast
import builtins
import doctest
import re
import textwrap
from dataclasses import dataclass, field

NAME_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(items|values|numbers|nums|data|elements|records|prices|scores|xs|seq|list)$"), "[1, 2, 3]"),
    (re.compile(r"(name|text|s|string|word|title|label|msg|message|code|sku|email)$"), "'abc'"),
    (re.compile(r"(rate|ratio|percent|percentage|discount|factor|weight)$"), "0.1"),
    (re.compile(r"^(n|count|x|y|a|b|i|j|k|num|number|amount|price|qty|quantity|total|size|limit|value|age|"
                r"divisor|dividend|width|height|length|index)$"), "1"),
    (re.compile(r"(flag|enabled|strict|verbose)$"), "True"),
    (re.compile(r"(mapping|config|options|params|kwargs|dict)$"), "{}"),
]
TYPE_VALUES = {"int": "1", "float": "1.0", "str": "'abc'", "bool": "True", "list": "[1, 2, 3]", "dict": "{}",
               "tuple": "(1, 2)", "set": "{1, 2}", "bytes": "b'abc'", "Decimal": "Decimal('1')"}
EMPTY_VALUES = {"list": "[]", "str": "''", "dict": "{}", "tuple": "()", "set": "set()", "bytes": "b''",
                "int": "0", "float": "0.0"}


@dataclass
class Proposal:
    name: str
    description: str
    target: str
    target_file: str
    category: str
    expected_behaviour: str
    code: str
    rationale: str
    strategy: str
    source_files: list[str] = field(default_factory=list)


def module_name(rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    parts = rel[:-3].split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


def _ann_name(ann: ast.expr | None) -> str | None:
    if ann is None:
        return None
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
        return {"List": "list", "Dict": "dict", "Sequence": "list", "Iterable": "list", "Tuple": "tuple",
                "Set": "set"}.get(ann.value.id, ann.value.id)
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return ann.value.split("[")[0]
    return None


def placeholder(arg: ast.arg, default: ast.expr | None) -> str | None:
    if default is not None:
        try:
            return ast.unparse(default)
        except Exception:  # pragma: no cover
            return None
    t = _ann_name(arg.annotation)
    if t and t in TYPE_VALUES:
        return TYPE_VALUES[t]
    lname = arg.arg.lower()
    for pat, val in NAME_HINTS:
        if pat.search(lname):
            return val
    return None


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.arg, ast.expr | None]]:
    args = fn.args.posonlyargs + fn.args.args
    defaults: list[ast.expr | None] = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
    out = list(zip(args, defaults))
    out += list(zip(fn.args.kwonlyargs, fn.args.kw_defaults))
    return [(a, d) for a, d in out if a.arg not in ("self", "cls")]


def _call(fn_name: str, params, overrides: dict[str, str]) -> str | None:
    pieces = []
    for arg, default in params:
        if arg.arg in overrides:
            val = overrides[arg.arg]
        else:
            if default is not None:
                continue  # leave defaults alone
            val = placeholder(arg, None)
            if val is None:
                return None
        pieces.append(f"{arg.arg}={val}")
    return f"{fn_name}({', '.join(pieces)})"


def _raised_names(fn) -> list[str]:
    names = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(exc, ast.Name):
                names.append(exc.id)
    return sorted(set(names))


def _value_for_condition(test: ast.expr, params: dict[str, ast.arg]) -> tuple[str, str, str] | None:
    """Return (param, value, explanation) that makes ``test`` true, if derivable."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        operand = test.operand
        if isinstance(operand, ast.Name) and operand.id in params:
            t = _ann_name(params[operand.id].annotation) or ""
            if t in EMPTY_VALUES:
                return operand.id, EMPTY_VALUES[t], f"`{operand.id}` is empty/falsy"
            hint = placeholder(params[operand.id], None) or ""
            if hint.startswith("["):
                return operand.id, "[]", f"`{operand.id}` is empty"
            if hint.startswith("'"):
                return operand.id, "''", f"`{operand.id}` is an empty string"
            return None
        if (isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name) and operand.func.id == "isinstance"
                and len(operand.args) == 2 and isinstance(operand.args[0], ast.Name) and operand.args[0].id in params):
            tname = ast.unparse(operand.args[1])
            bad = "'not-a-number'" if any(k in tname for k in ("int", "float", "Decimal")) else "12345"
            return operand.args[0].id, bad, f"`{operand.args[0].id}` is not an instance of {tname}"
        return None
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        # len(p) == 0 / len(p) < 1
        if (isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len" and left.args
                and isinstance(left.args[0], ast.Name) and left.args[0].id in params and isinstance(right, ast.Constant)):
            if (isinstance(op, ast.Eq) and right.value == 0) or (isinstance(op, ast.Lt) and right.value == 1):
                return left.args[0].id, "[]", f"`{left.args[0].id}` is empty"
            return None
        if not (isinstance(left, ast.Name) and left.id in params):
            return None
        p = left.id
        if isinstance(op, (ast.Is,)) and isinstance(right, ast.Constant) and right.value is None:
            return p, "None", f"`{p}` is None"
        if isinstance(right, ast.UnaryOp) and isinstance(right.op, ast.USub) and isinstance(right.operand, ast.Constant):
            c = -right.operand.value
        elif isinstance(right, ast.Constant) and isinstance(right.value, (int, float)) and not isinstance(right.value, bool):
            c = right.value
        elif isinstance(right, ast.Constant) and isinstance(right.value, str) and isinstance(op, ast.Eq):
            return p, repr(right.value), f"`{p}` == {right.value!r}"
        else:
            if isinstance(op, ast.NotIn) and isinstance(right, (ast.Tuple, ast.List, ast.Set, ast.Name)):
                return p, "'__invalid_value__'", f"`{p}` is not one of the allowed values"
            return None
        step = 1 if isinstance(c, int) else 0.5
        mapping = {ast.Eq: c, ast.Lt: c - step, ast.LtE: c, ast.Gt: c + step, ast.GtE: c}
        for op_type, val in mapping.items():
            if isinstance(op, op_type):
                return p, repr(val), f"`{p}` {ast.unparse(test).split(p, 1)[1].strip()}"
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        for v in test.values:
            r = _value_for_condition(v, params)
            if r:
                return r
    return None


def _safe_ident(s: str) -> str:
    return re.sub(r"\W+", "_", s).strip("_").lower()[:60] or "case"


def _header(mod: str, needs_pytest: bool, extra: str = "") -> str:
    lines = ["# Generated by TestPilot AI — review before approving."]
    if needs_pytest:
        lines.append("import pytest")
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def generate_for_file(rel: str, source: str, *, max_per_function: int = 4) -> list[Proposal]:
    mod = module_name(rel)
    if mod is None:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    proposals: list[Proposal] = []
    uses_decimal = "Decimal" in source

    proposals.append(Proposal(
        name=f"test_import_{_safe_ident(mod)}",
        description=f"Module '{mod}' can be imported without raising.",
        target=mod, target_file=rel, category="unit",
        expected_behaviour="Importing the module completes without an exception.",
        code=_header(mod, False) + f"\n\ndef test_import_{_safe_ident(mod)}():\n    import {mod}  # noqa: F401\n",
        rationale="Baseline smoke test: every other test for this module depends on it importing cleanly.",
        strategy="import", source_files=[rel]))

    targets: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str | None]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            targets.append((node.name, node, None))
    for fn_name, fn, _cls in targets:
        if isinstance(fn, ast.AsyncFunctionDef):
            continue  # async needs an event-loop plugin; skipped deliberately
        params = _params(fn)
        pmap = {a.arg: a for a, _ in params}
        count = 0
        custom_exc = [n for n in _raised_names(fn) if not hasattr(builtins, n)]
        imp = f"from {mod} import {', '.join([fn_name] + custom_exc)}"
        if uses_decimal:
            imp += "\nfrom decimal import Decimal"

        # --- doctest examples -------------------------------------------------
        doc = ast.get_docstring(fn) or ""
        try:
            examples = doctest.DocTestParser().get_examples(doc)
        except ValueError:
            examples = []
        for i, ex in enumerate(examples[:3]):
            src = ex.source.strip()
            want = ex.want.strip()
            if not src or "\n" in src:
                continue
            if ex.exc_msg is not None or want.startswith("Traceback"):
                exc_name = (want.strip().splitlines()[-1].split(":")[0].strip().split(".")[-1]) if want else None
                if not exc_name or not exc_name.isidentifier():
                    continue
                body = f"    with pytest.raises({exc_name}):\n        {src}\n"
                expected = f"`{src}` raises {exc_name}, as documented in the docstring."
                needs = True
            else:
                try:
                    ast.literal_eval(want)
                except (ValueError, SyntaxError):
                    continue
                body = f"    assert {src} == {want}\n"
                expected = f"`{src}` returns `{want}`, as documented in the docstring."
                needs = False
            tname = f"test_{fn_name}_docstring_example_{i + 1}"
            proposals.append(Proposal(
                name=tname, description=f"Docstring example #{i + 1} of {fn_name}.", target=f"{mod}.{fn_name}",
                target_file=rel, category="regression", expected_behaviour=expected,
                code=_header(mod, needs, imp) + f"\n\ndef {tname}():\n{body}",
                rationale="The expected value is taken verbatim from the function's own docstring example.",
                strategy="doctest", source_files=[rel]))
            count += 1

        # --- explicit raise guards ---------------------------------------------
        for node in ast.walk(fn):
            if count >= max_per_function:
                break
            if not isinstance(node, ast.If):
                continue
            first = node.body[0] if node.body else None
            if not isinstance(first, ast.Raise) or first.exc is None:
                continue
            exc = first.exc.func if isinstance(first.exc, ast.Call) else first.exc
            if not isinstance(exc, ast.Name):
                continue
            cond = _value_for_condition(node.test, pmap)
            if not cond:
                continue
            param, value, why = cond
            call = _call(fn_name, params, {param: value})
            if call is None:
                continue
            tname = f"test_{fn_name}_raises_{exc.id.lower()}_when_{_safe_ident(param)}_invalid"
            if any(p.name == tname for p in proposals):
                continue
            category = "input-validation" if exc.id in ("ValueError", "TypeError") else "error-handling"
            proposals.append(Proposal(
                name=tname, description=f"{fn_name} raises {exc.id} when {why}.", target=f"{mod}.{fn_name}",
                target_file=rel, category=category,
                expected_behaviour=f"Calling `{call}` raises {exc.id} (line {node.lineno}: `{ast.unparse(node.test)}`).",
                code=_header(mod, True, imp) + f"\n\ndef {tname}():\n    with pytest.raises({exc.id}):\n        {call}\n",
                rationale=f"The function explicitly raises {exc.id} at line {first.lineno} when "
                          f"`{ast.unparse(node.test)}`. Other arguments use placeholder values — check they are "
                          "valid so the guard under test is the one that fires.",
                strategy="guard", source_files=[rel]))
            count += 1

        # --- heuristic edge cases ------------------------------------------------
        declared = _raised_names(fn)
        for arg, default in params:
            if count >= max_per_function:
                break
            if default is not None:
                continue
            t = _ann_name(arg.annotation)
            hint = placeholder(arg, None) or ""
            if t in ("list", "tuple", "set") or (t is None and hint.startswith("[")):
                edge, label = "[]", "empty_list"
            elif t == "str" or (t is None and hint.startswith("'")):
                edge, label = "''", "empty_string"
            elif t in ("int", "float") or (t is None and hint in ("1", "0.1")):
                edge, label = "0", "zero"
            else:
                continue
            call = _call(fn_name, params, {arg.arg: edge})
            if call is None:
                continue
            tname = f"test_{fn_name}_handles_{label}_{_safe_ident(arg.arg)}"
            if any(p.name == tname for p in proposals):
                continue
            allowed = ", ".join(declared) if declared else ""
            if declared:
                body = (f"    try:\n        {call}\n    except ({allowed}{',' if len(declared) == 1 else ''}):\n"
                        f"        pass  # explicitly raised by the function — acceptable\n")
                expected = (f"`{call}` either returns normally or raises one of the exceptions the function "
                            f"explicitly raises ({allowed}). Any other exception indicates an unhandled edge case.")
            else:
                body = f"    {call}\n"
                expected = f"`{call}` completes without raising (the function declares no exceptions)."
            proposals.append(Proposal(
                name=tname, description=f"Edge case: {fn_name} with {label.replace('_', ' ')} for '{arg.arg}'.",
                target=f"{mod}.{fn_name}", target_file=rel, category="edge-case" if label != "zero" else "boundary",
                expected_behaviour=expected,
                code=_header(mod, False, imp) + f"\n\ndef {tname}():\n{body}",
                rationale="Heuristic edge-case test: the expected behaviour is an assumption (no unexpected "
                          "exception), not derived from documentation. Confirm it matches the intended contract "
                          "before approving.",
                strategy="edge", source_files=[rel]))
            count += 1
    return proposals


def validate_python_test(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"syntax_ok": False, "error": f"line {exc.lineno}: {exc.msg}"}
    tests = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")]
    forbidden = sorted({n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in ("eval", "exec", "__import__")})
    return {"syntax_ok": True, "test_functions": tests, "has_tests": bool(tests), "forbidden_calls": forbidden}


def indent(code: str) -> str:  # pragma: no cover - helper for templates
    return textwrap.indent(code, "    ")
