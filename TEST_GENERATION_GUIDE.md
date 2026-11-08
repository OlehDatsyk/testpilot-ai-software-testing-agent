# Test Generation Guide

## Context collection

Generation runs as a worker job on the latest snapshot and analysis. Candidate files are supported source files with public symbols (from the analysis), prioritised by testing gaps; optionally restricted to the files you pass. Up to 60 files are considered; AI is applied to at most 5 files per job.

## Rule-based generators (always available, no AI)

### Python → pytest (`generators/python_tests.py`)
For each module and each public, synchronous, module-level function:

| Strategy | Source of truth | Category |
|---|---|---|
| `import` | module path derived from the file path (`src/` layout supported) | unit |
| `doctest` | `>>>` examples in the docstring; expected value copied verbatim (or the documented exception) | regression |
| `guard` | `if <condition on a parameter>: raise X` — the generator derives an input that satisfies the condition (`==`, `<`, `<=`, `>`, `>=`, `is None`, `not p`, `len(p) == 0`, `not isinstance`, `not in`) and asserts `pytest.raises(X)` | input-validation / error-handling |
| `edge` | **heuristic** — empty list, empty string or zero for a parameter; asserts the call returns or raises only an exception the function itself raises | edge-case / boundary |

Placeholder values for the other parameters come from defaults, type annotations, or conservative name hints; functions where no value can be derived are skipped rather than guessed. Custom exception classes are imported from the module. Heuristic edge tests say so in their rationale and must be reviewed.

### JavaScript / TypeScript → Vitest (`generators/js_tests.py`)
For ESM modules with exported functions: an *exports* test, `@example fn(args) // => value` JSDoc examples, and `if (param <op> literal) throw new X` / `if (!xs || xs.length === 0) throw` guards. Tests use Vitest globals (`describe/it/expect`) and import the module relatively from `testpilot_generated/`.

## AI-assisted generation (optional)

With `AI_PROVIDER=anthropic` and `AI_API_KEY` set, ticking *Include AI suggestions* sends, per file: the file path, language, framework instructions, existing test file names, an optional focus, and the source (truncated to 14 000 characters, flagged when truncated). The model must return `AITestSuggestions` (Pydantic schema: name, description, target, category, expected behaviour, rationale, code). Each result is validated: Python must parse and contain a `test*` function and no `eval`/`exec`/`__import__`; JS must have balanced brackets, an `it`/`test` call and no `eval`. Invalid outputs are discarded. Stored proposals are marked `generator = ai:<model>` and their rationale starts with "AI suggestion". If the provider fails, rule-based generation still completes and the job result explains why AI was skipped.

## Supported languages and frameworks

Python 3 with pytest (+ coverage.py at run time); JavaScript and TypeScript with Vitest (+ v8 coverage). TypeScript is executed through Vitest's esbuild transform; no type-checking happens at run time.

## Test categories

unit · regression · input-validation · error-handling · edge-case · boundary · integration · api (the last two only from AI suggestions).

## Review and approval workflow

1. Every new test is **proposed** — it cannot be executed (the API returns 422).
2. Reviewers can read target, expected behaviour, rationale and code; **edit** the code (re-validated; status returns to *proposed*); **approve** (blocked if validation failed) or **reject**; bulk actions are available.
3. Only approved tests are written into the sandbox workspace for a run, as `testpilot_generated/test_tp_<id>_*.py` or `tp_<id>_*.test.(js|ts)`; results are linked back to the generated test.
4. *Export approved* produces a zip for you to commit yourself. TestPilot never writes to connected repositories.
5. Re-running generation does not duplicate existing (non-rejected) tests with the same name and file.

## Known limitations

Class methods, async functions and CommonJS exports are not targeted by the rule-based generators. Placeholder arguments may trigger a different code path than intended — that is why review is mandatory. Generated tests never claim to be correct until executed; an executed failure may indicate a defect **or** a wrong expectation — the failure view shows both possibilities.
