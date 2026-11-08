"""Deterministic failure analysis from real test output.

Extracts the exception type and the deepest project frame from the traceback
and maps common exception types to explanations. Output is labelled as a
*suggestion*; the raw message and traceback are always kept unchanged.
"""
from __future__ import annotations

import re

PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)|^([\w./\\-]+\.py):(\d+):', re.M)
JS_FRAME = re.compile(r"(?:at .*?\(|❯ |at )([^\s()]+\.(?:[cm]?[jt]sx?)):(\d+):(\d+)")
EXC_LINE = re.compile(r"^(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning|Interrupt|AssertionError))\b:?\s*(.*)$", re.M)

EXPLANATIONS = {
    "AssertionError": ("An assertion in the test did not hold: the actual value differed from the expected value.",
                       ["The implementation returns a different value than the test expects",
                        "The test's expected value is wrong or based on an incorrect assumption"],
                       ["Compare the 'assert' line's left and right values in the traceback",
                        "Confirm the intended behaviour, then fix either the code or the expectation"]),
    "ZeroDivisionError": ("A division or modulo operation used zero as the divisor.",
                          ["An empty collection was used to compute an average/ratio",
                           "A numeric argument that can legitimately be zero is not guarded"],
                          ["Guard the division (e.g. 'if not items:') and return a defined value or raise a clear error"]),
    "TypeError": ("An operation received a value of an unsupported type, or a function got the wrong arguments.",
                  ["None or a wrong type is passed where a number/string/sequence is expected",
                   "The function signature changed and callers were not updated"],
                  ["Check the argument types at the failing line", "Add input validation with a clear error"]),
    "ValueError": ("A function received an argument of the right type but an invalid value.",
                   ["Input validation rejected the value", "Parsing of a string failed"],
                   ["Check whether the input is legitimately invalid (then assert the error) or whether validation is too strict"]),
    "KeyError": ("A dictionary lookup used a key that does not exist.",
                 ["Missing key in input data", "Typo in the key name"],
                 ["Use dict.get with a default or validate required keys up front"]),
    "IndexError": ("A sequence index was outside the valid range.",
                   ["Empty list accessed with [0] or [-1]", "Off-by-one error in a loop bound"],
                   ["Check the sequence length before indexing"]),
    "AttributeError": ("An attribute or method was accessed on an object that does not have it (often None).",
                       ["A function returned None unexpectedly", "Wrong object type passed in"],
                       ["Check for None before attribute access", "Verify the object's type"]),
    "ModuleNotFoundError": ("A module could not be imported in the test environment.",
                            ["A third-party dependency is not installed in the sandbox (network is disabled)",
                             "The import path does not match the repository layout"],
                            ["Check the import path", "Dependencies must be pre-installed in the runner image"]),
    "ImportError": ("An import failed.", ["Missing dependency or circular import"], ["Check the import chain in the traceback"]),
    "NameError": ("A name was used that is not defined.", ["Typo or missing import"], ["Define or import the name"]),
    "RecursionError": ("Maximum recursion depth was exceeded.", ["Missing or unreachable base case"],
                       ["Check the recursion termination condition"]),
    "Failed: DID NOT RAISE": ("The test expected an exception but the code returned normally.",
                              ["The input validation the test relies on does not exist or is incomplete",
                               "Placeholder arguments triggered a different code path"],
                              ["Check whether the function should reject this input", "Review the test's arguments"]),
}


def analyse_failure(message: str | None, traceback: str | None, language: str) -> dict:
    text = "\n".join(x for x in (message, traceback) if x)
    exc_type, exc_msg = None, None
    if "DID NOT RAISE" in text:
        exc_type = "Failed: DID NOT RAISE"
    else:
        matches = EXC_LINE.findall(text)
        if matches:
            exc_type, exc_msg = matches[-1][0].split(".")[-1], matches[-1][1][:300]
    frames = []
    if language == "python":
        for m in PY_FRAME.finditer(text):
            f, ln = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            if "site-packages" in f or "/usr/" in f or "_pytest" in f:
                continue
            frames.append({"file": _rel(f), "line": int(ln)})
    else:
        for m in JS_FRAME.finditer(text):
            if "node_modules" in m.group(1):
                continue
            frames.append({"file": _rel(m.group(1)), "line": int(m.group(2))})
    key = exc_type if exc_type in EXPLANATIONS else None
    if key is None and exc_type and exc_type.endswith("Error") and "Assertion" in exc_type:
        key = "AssertionError"
    meaning, causes, fixes = EXPLANATIONS.get(key or "", (
        "The test failed; the exception type is not in the built-in knowledge base.",
        ["See the raw traceback below"], ["Inspect the failing line and the raw output"]))
    return {
        "kind": "rule-based-suggestion",
        "exception_type": exc_type,
        "exception_message": exc_msg,
        "location": frames[-1] if frames else None,
        "frames": frames[-5:],
        "meaning": meaning,
        "possible_causes": causes,
        "suggested_fixes": fixes,
        "disclaimer": "Automated suggestion derived from the recorded output. Verify before acting on it.",
    }


def _rel(f: str) -> str:
    f = f.replace("\\", "/")
    return f.split("/work/", 1)[1] if "/work/" in f else f
