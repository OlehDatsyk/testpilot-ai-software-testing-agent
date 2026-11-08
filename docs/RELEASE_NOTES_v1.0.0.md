# TestPilot AI v1.0.0 — Initial Release

AI-powered software testing platform for repository analysis, automated test generation, test execution, bug detection and quality assurance.

## Highlights
- **Repository analysis** of Python, JavaScript and TypeScript projects from public GitHub repos, private repos (GitHub OAuth), archive uploads or the bundled demo: languages, frameworks, dependencies, test setup, build scripts, testing gaps.
- **Static analysis** with Python AST rules, Ruff and a JS/TS rule engine — every finding cites the exact source line and is labelled *definite* or *potential*, with review statuses that persist across re-analysis.
- **Test generation** for pytest and Vitest from docstring/JSDoc examples, explicit error guards and flagged heuristic edge cases; optional AI suggestions (Anthropic) validated by schema and syntax.
- **Human approval** before anything runs; approved tests can be exported — connected repositories are never modified.
- **Isolated execution** in a per-job Docker sandbox (no network, non-root, read-only root FS, no capabilities, CPU/memory/PID limits, timeout), verified by in-sandbox hostile probes. Execution can be disabled and the rest of the platform keeps working.
- **Results & failure analysis**: raw output preserved, rule-based explanations, optional AI analysis — always labelled as suggestions.
- **Coverage** from coverage.py and Vitest v8, shown only when measured.
- **Bug reports**, **run comparison**, **PDF/HTML QA reports** separating MEASURED / SUGGESTED / LIMITATION, an **analytics dashboard** and a grounded **AI testing assistant**.

## Technology
React 18 · TypeScript · Vite · Tailwind CSS 4 · Recharts — FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL/SQLite — Docker runner with pytest, coverage.py, Node 22, Vitest 3.

## Installation
Windows: `Start App.bat` · macOS/Linux: `Start App.command` · or Docker Compose — see INSTRUCTION.md. Real execution requires Docker and `docker build -t testpilot-runner:latest execution-runner`.

## Verified
Backend 83 tests passed (incl. 5 real sandbox tests) on SQLite; 78 passed / 5 skipped on PostgreSQL 16; frontend 9 tests passed; production build clean. See TESTING.md.

## Known limitations
No dependency installation inside the sandbox; ESLint/tsc/mypy not integrated; JS/TS analysis is heuristic; container (not VM) isolation, not independently audited; Render deployment prepared but not deployed, with execution disabled on Render; live GitHub OAuth and live AI calls not tested; ephemeral storage on Render free tier.
