# Installation & Usage Guide

## 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ (3.12 tested) | backend and worker |
| Node.js / npm | 20+ (22/24 tested) | frontend |
| Docker Desktop / Engine | 24+ | **optional** — real test execution, Compose stack |
| PostgreSQL | 14+ (16 tested) | optional locally (SQLite is the default) |

## 2. One-click start

* **Windows:** `Start App.bat` · **macOS/Linux:** `Start App.command`

Steps performed: check Python/Node → create `.env` from `.env.example` if missing (random `SECRET_KEY`, never overwrites) → create `backend/.venv` and install `backend/requirements.txt` if missing → `npm ci` in `frontend/` if needed → if `EXECUTION_PROVIDER=docker`, check Docker and build `testpilot-runner:latest` on first run → start API (`:8000`), worker and frontend (`:5173`) → wait for `/health/ready` → open the browser. If a step fails, the script stops with an explanation; it never deletes data.

## 3. Manual installation

```bash
cp .env.example .env            # then edit SECRET_KEY etc.
```

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```
(Windows: `.venv\Scripts\pip`)

```bash
cd frontend && npm ci
```

Run (three terminals):

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
```

```bash
cd backend && .venv/bin/python -m app.worker
```

```bash
cd frontend && npm run dev
```

### Docker Compose (PostgreSQL + API + worker)

```bash
docker compose up --build
```
Then `cd frontend && npm run dev`. Execution is disabled in Compose on purpose (no Docker socket is mounted into containers).

## 4. Configuration

See `.env.example` — every variable is documented there and in the README table. Blank values fall back to safe defaults. The frontend reads only `VITE_API_BASE_URL` (public).

## 5. Database

* **SQLite (default):** `backend/data/testpilot.db`, tables created automatically (`AUTO_CREATE_TABLES=true`).
* **PostgreSQL:** set `DATABASE_URL=postgresql://user:pass@host:5432/db`, `AUTO_CREATE_TABLES=false`, then:

```bash
cd backend && .venv/bin/alembic upgrade head
```

Migrations live in `backend/alembic/versions/`. Never use `alembic downgrade` on production data.

## 6. Enabling real test execution

```bash
docker build -t testpilot-runner:latest execution-runner
```
Set `EXECUTION_PROVIDER=docker` in `.env` and restart the **worker**. *Test Runs* shows the provider status. Read [EXECUTION_SECURITY.md](EXECUTION_SECURITY.md) first.

## 7. Using TestPilot

1. **Register** (a personal workspace is created) and sign in.
2. **Create a project** — *Projects → New project*: GitHub (public by URL; private after connecting in Settings), **Upload archive** (.zip/.tar.gz), **Manual**, or **Demo**.
3. **Repository Analysis** runs automatically after import (or click *Run analysis*). Tabs: *Overview* (languages, frameworks, dependencies, test commands, analysers that ran), *Static analysis findings*, *Testing gaps*.
4. **Review findings** — expand a finding to see the exact source line, description and suggestion; set *open / accepted / false positive / resolved* (kept across re-analysis); *Create bug report*.
5. **Test Generation** — *Generate tests* (tick *Include AI suggestions* if an AI provider is configured). Each proposal shows target, category, expected behaviour, rationale, code and validation.
6. **Approve** — approve/reject individually or in bulk; edit code if needed (edits require re-approval). *Export approved* downloads a zip for your own repository — TestPilot never writes to it.
7. **Test Runs → New test run** — choose language, include existing tests, pick approved generated tests, *Start run*. Status updates come from the worker.
8. **Failure analysis** — open a run, expand a failed test: raw message and stack trace, a rule-based explanation (suggestion), and optionally *AI failure analysis*. *Raw log* shows runner output.
9. **Coverage** — line/branch (and function for Vitest) coverage per file, uncovered files, history per tool.
10. **Bug Reports** — edit, set severity/status, add notes, export Markdown/JSON.
11. **Compare runs** — on *Test Runs*, pick two runs.
12. **Reports** — generate PDF/HTML for the latest (or chosen) run; download previous reports.
13. **AI Testing Assistant** — ask about architecture, failures, coverage, findings, release readiness.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| Jobs stay *Queued* | The worker is not running: `python -m app.worker` (Settings → Platform status shows queue depth) |
| Run says *Execution unavailable* | Expected when `EXECUTION_PROVIDER=disabled`; otherwise start Docker and build the runner image; the reason is shown on the run |
| Run *failed* with "No test results were produced" | Tests could not be collected — open *Raw log* (often a missing third-party dependency; the sandbox has no network) |
| *Cannot reach the TestPilot API* in the UI | Start the API; check `VITE_API_BASE_URL`; check `CORS_ORIGINS` contains the frontend origin |
| Registration says email invalid | Reserved domains such as `.local` are rejected by the email validator; use a real-format address |
| GitHub lookup 429 | GitHub rate limit; connect GitHub or set `GITHUB_PUBLIC_TOKEN` |
| `DLL load failed … filename or extension is too long` (Windows) | The project path is too long for some native wheels (e.g. psycopg). Move the repository to a shorter path such as `C:\dev\testpilot` |
| Report download returns 410 | Storage was reset (e.g. ephemeral hosting) — regenerate the report |
