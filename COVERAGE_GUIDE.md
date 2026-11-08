# Coverage Guide

## Tools

| Language | Tool | Invocation inside the sandbox | Metrics |
|---|---|---|---|
| Python | coverage.py 7 | `coverage run --branch --source=/work --omit=<tests, generated tests, conftest> -m pytest …` then `coverage json` | line %, branch %, per-file statements/covered/missing lines |
| JavaScript / TypeScript | Vitest v8 provider (`@vitest/coverage-v8`) | `vitest run --coverage.enabled --coverage.reporter=json-summary` | line %, branch %, function %, per-file line/branch/function % |

Test files and `testpilot_generated/` are excluded from the measured code.

## What is shown

* Per run: line, branch and function coverage — function coverage is shown as "not reported by coverage.py" for Python, never as 0 %.
* Coverage page: latest report per project, per-file table sorted by lowest coverage with missing line numbers (Python), *uncovered source files* (supported files never imported during the run), change versus the previous run **of the same tool**, and history per tool.
* Run comparison: coverage delta only when both runs used the same tool.
* Dashboard: coverage trend per run.

## When coverage is unavailable

No values are estimated. If execution is disabled/unavailable, the run timed out before the report was written, the artefact was malformed/oversized, or zero lines were measured, no coverage record is stored and the UI says "Coverage was not measured".

## Interpreting coverage

Coverage indicates which code **was exercised** by the tests. It does **not** show whether assertions were meaningful, whether edge cases were tested, or whether the code is correct. A test that calls a function without asserting anything raises coverage just as much as a thorough one. Use coverage to find untested code, not as a quality score.
