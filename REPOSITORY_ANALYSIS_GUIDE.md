# Repository Analysis Guide

## Getting code into TestPilot

| Source | How | Notes |
|---|---|---|
| Public GitHub repository | `GET /repos/{owner}/{repo}` (metadata, default branch), `/branches`, `/commits/{ref}` (SHA), then `/tarball/{sha}` | No credentials needed; optional `GITHUB_PUBLIC_TOKEN` raises rate limits |
| Private GitHub repository | Same calls with the user's OAuth token (decrypted only in the worker) | Requires *Settings → GitHub → Connect incl. private repos* |
| Archive upload | `.zip`, `.tar.gz`, `.tgz` | Size-limited at upload, extracted by the worker |
| Demo | Copies `demo-project/` | Labelled demo data |

All GitHub calls are read-only `GET`s. Rate limiting (403/429 with `x-ratelimit-remaining: 0`) is reported with the reset time; 401/404 are reported clearly and not retried.

## Snapshot creation (untrusted input)

`services/archive.py` extracts archives with: rejection of absolute paths, drive letters and `..`; no symlinks, hard links or device files (recorded as skipped); a running byte budget (`MAX_EXTRACTED_SIZE_MB`) that aborts decompression bombs; a file-count limit (`MAX_FILES_PER_SNAPSHOT`); per-file size limit; skipping `.git`, `node_modules`, virtualenvs, caches, `dist`, `build`, coverage output. A single top-level directory (as in GitHub tarballs) is stripped. Snapshots are stored under `STORAGE_ROOT/snapshots/<project>/<uuid>/`; metadata (ref, commit SHA, counts, skipped files) goes to the database.

## File discovery & language detection

Every regular file is listed. Binary/lock extensions are skipped and recorded; files above `MAX_FILE_SIZE_KB` are listed but not parsed. Languages are detected by extension: Python (`.py`), JavaScript (`.js .mjs .cjs .jsx`), TypeScript (`.ts .tsx .mts .cts`) are *supported*; others (Go, Rust, Java, …) are reported but not analysed.

Test files: `test_*.py`, `*_test.py`, `conftest.py`, `*.test.*`, `*.spec.*`, and files under `__tests__/`.

## Framework & dependency detection

| Input | What is read |
|---|---|
| `requirements*.txt` | package specifiers (`dev`/`test` files → dev dependencies) |
| `pyproject.toml` | `[project].dependencies`, optional dependencies, Poetry dependencies, `[tool.pytest]` |
| `setup.py`, `setup.cfg`, `pytest.ini`, `tox.ini`, `mypy.ini`, `ruff.toml`, `.coveragerc` | presence |
| `package.json` | name, dependencies, devDependencies, scripts (`test*` → test commands; build/dev/start/lint/typecheck → build scripts), module type |
| `vite/vitest/jest/playwright.config.*`, `tsconfig.json` | framework presence |
| Python imports (regex over source, not executed) | FastAPI, Django, Flask, pytest, SQLAlchemy, … |

## Static analysis

| Analyser | Scope | Method label |
|---|---|---|
| Python AST rules | syntax errors; bare `except`; swallowed `except Exception: pass`; mutable defaults; `== None`; `is` with literals; `assert (tuple)`; `eval`/`exec`; `shell=True`; division by literal zero; division by `len()`; hard-coded secret-like assignments; builtin-shadowing parameters; cyclomatic complexity > 10 | `python-ast` |
| Ruff (`--isolated`, rules `E7,E9,F,B`) | pyflakes + bugbear + selected pycodestyle; repository Ruff config is ignored | `ruff` |
| JS/TS rules | loose equality, `eval`/`new Function`, `debugger`, empty `catch`, `var`, `console.log`, explicit `any` (TS), `innerHTML`/`dangerouslySetInnerHTML`, `parseInt` without radix, unbalanced braces — after blanking strings/comments | `js-rules` |
| ESLint, `tsc`, mypy | not run | shown as *not implemented* |

Each finding stores rule, file, line/column (from the parser — never invented), severity (critical/high/medium/low/info), category, description, **evidence = the exact source line read from the file**, suggestion, method, certainty (*definite* when the rule match is unambiguous, *potential* when human judgement is needed) and review status. Ruff duplicates of equivalent AST rules on the same line are collapsed. A SHA-256 fingerprint (rule + file + evidence) carries review decisions across re-analyses.

## Testing gaps

A module is listed as a gap when no test file path or content mentions its module name. This is a heuristic and is labelled as such; measured coverage (after a run) is authoritative.

## Limitations

Monorepos are analysed as one tree; generated code is analysed like any code; files that are not UTF-8 are skipped; the JS/TS rule engine is not a parser; no cross-file data-flow analysis.
