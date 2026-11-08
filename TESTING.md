# Testing

All results below were produced on **2026-11-08** from the code in this repository. Nothing is reported as passed unless it executed.

## Environment

| Item | Version |
|---|---|
| OS | Windows 11 Home (10.0.26200) |
| Python | 3.12.10 (venv) · pytest 8.3 |
| Node.js / npm | 24.20.0 / 11.19.0 · Vitest 3.2.4 · TypeScript 5.6.3 |
| Docker | 29.9.2 (Linux engine) · runner image `testpilot-runner:latest` built from `execution-runner/` |
| PostgreSQL | 16 (`postgres:16-alpine`), tests run from a `python:3.12-slim` container |

## Commands

```bash
cd backend && python -m ruff check app tests && python -m pytest -rs
```

```bash
TEST_DATABASE_URL=postgresql://user:pass@host:5432/db python -m pytest -rs   # PostgreSQL run
```

```bash
cd backend && alembic upgrade head && alembic check && alembic downgrade base
```

```bash
cd frontend && npx tsc --noEmit -p . && npm test && npm run build
```

## Results

| Suite | Result |
|---|---|
| Ruff (backend `app/` + `tests/`) | All checks passed |
| Backend, SQLite, Docker available | **83 passed**, 0 failed, 0 skipped (84 s) |
| Backend, PostgreSQL 16, no Docker in container | **78 passed, 5 skipped** (the 5 sandbox tests: "Docker CLI not found") |
| Alembic on PostgreSQL | `upgrade head` ✔ · `check` → "No new upgrade operations detected" ✔ · `downgrade base` ✔ (also ✔ on SQLite) |
| Frontend type-check (`tsc --noEmit`) | ✔ no errors |
| Frontend unit tests (Vitest + Testing Library) | **9 passed** |
| Frontend production build (`vite build`) | ✔ (JS 705 kB / 200 kB gzip — warning-level chunk size, see Known issues) |
| Backend container (`backend/Dockerfile`) | built; `alembic upgrade head` on start; `/health/ready` → ready; registration OK; runs as non-root user `app` |
| `docker compose config` | valid |

### Backend test coverage by area (`backend/tests/`)

| File | Tests | Covers |
|---|---|---|
| `test_auth_permissions.py` | 10 | register/login/me, password hashing & strength, duplicates, wrong password, 401 on protected routes, logout revocation, **cross-user isolation on 10 project endpoints**, path traversal in file viewer, health endpoints, capabilities without secrets |
| `test_archives.py` | 13 | zip-slip (5 variants), decompression bomb, file-count limit, tar symlink/hardlink, tar traversal, garbage input, upload type check, malicious upload → failed job without snapshot, valid upload → analysis |
| `test_analysis_generation.py` | 11 | structure detection, Python findings with exact evidence lines, potential vs definite, syntax errors, JS rules ignoring strings/comments, demo JS findings, Python/JS generators (doctest, guard, edge, export, JSDoc), validators |
| `test_workflow_api.py` | 11 | demo import → analysis (Ruff de-dup) → generation (no duplicates), unapproved tests rejected (422), edits require re-approval, **execution disabled → `execution_unavailable` with zero results/coverage**, queued-run cancellation, review status persisted across re-analysis, bug reports from evidence (no invented fields) + export + comparison, PDF/HTML reports, grounded assistant, AI analysis 503 without provider, delete |
| `test_integrations_units.py` | 26 | GitHub URL/branch validation, mocked GitHub API import (**only GET requests**), error mapping (404/429/400), OAuth not configured, forged OAuth state, token encryption, token never returned, log redaction, JUnit parsing incl. DOCTYPE/ENTITY rejection, coverage parsing, failure analysis rules, AI generation validation with a fake provider (invalid/forbidden outputs discarded), AI failure fallback, assistant context excludes secrets |
| `test_config_security.py` | 7 | production SECRET_KEY / local_trusted / wildcard CORS refusal, embedded worker requires disabled execution, Render URL normalisation, local_trusted refuses non-demo code, default provider disabled, embedded worker loop processes jobs and stops |
| `test_execution_sandbox.py` | 5 | **real Docker runs**: demo Python (18 tests: 16 passed / 2 failed — both deliberate defects; ZeroDivisionError located at `inventory/pricing.py:26`; coverage.py measured), demo JavaScript (Vitest, all passed, v8 coverage), **isolation probes inside the sandbox** (no secret/canary env vars, uid 65534, no network, read-only root FS, no Docker socket/host mounts, NoNewPrivs=1, CapEff=0), timeout enforcement (600 s sleep → `timed_out` in < 60 s), fork bomb contained |

## Manual verification (browser, 2026-11-08)

Performed against the running stack (API + worker with `EXECUTION_PROVIDER=docker` + Vite dev server) in a browser:

| Flow | Result |
|---|---|
| Register → empty-state onboarding → *Load demo project* | ✔ (found & fixed: field-level validation messages were hidden — now shown) |
| Repository analysis overview, analysers panel, findings with evidence, status changes | ✔ (fixed: filter selects stretched full width; Ruff E722 severity raised to medium) |
| Generate → expand proposal → bulk approve | ✔ 15 proposals |
| New Python run in the sandbox → results → failure detail → bug report from failure | ✔ 18 executed, 16 passed, 2 failed; coverage 75.0 % lines / 55.6 % branches (fixed: long path overlap) |
| JavaScript run | ✔ 8/8 passed, v8 coverage 81.25 % lines |
| Report generation, assistant | ✔ (fixed: release question routing, Markdown list rendering, snake_case paths mangled as italics, complexity list included test files) |
| Coverage page | ✔ (fixed: "change vs previous" compared a Python run with a JavaScript run — now same-tool only, also in the API comparison) |
| Screenshots | 14 captured with `scripts/capture-screenshots.mjs` (Playwright-core + Edge) into `docs/screenshots/` |

## Not tested

* **Live Render deployment** — not performed. `render.yaml` checked against the current Blueprint spec only.
* **Live GitHub OAuth** with a real OAuth App, and imports from real public/private GitHub repositories over the network (covered only by a mocked GitHub API).
* **Live Anthropic API calls** — the AI layer was tested with a fake provider; no API key was used.
* `Start App.bat` and `Start App.command` were not run end-to-end (they open service windows); `Start App.command` passed `bash -n` syntax checking and `scripts/prepare_env.py` was executed.
* Execution on macOS/Linux hosts; `local_trusted` provider end-to-end.
* Load/performance testing, multi-worker concurrency under load, browser compatibility beyond Chromium-based browsers, accessibility audit.

## Known issues

* Frontend bundle is a single 705 kB chunk (Recharts); route-level code splitting is a possible improvement.
* On Windows, very long project paths can break native Python wheels (`psycopg`, `greenlet`): "DLL load failed … filename or extension is too long". Clone into a short path.
* `npm install` warns that some package install scripts were not run (npm's install-scripts policy); the build and tests work without them.
