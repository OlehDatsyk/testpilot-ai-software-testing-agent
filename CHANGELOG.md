# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [1.0.0] — 2026-11-08 — Initial release

First public version. No earlier releases exist.

### Added
- Authentication (register, login, logout with token revocation), personal workspaces, workspace-scoped authorisation.
- Projects from public GitHub repositories, private repositories via GitHub OAuth, `.zip`/`.tar.gz` uploads, manual projects and a labelled demo project.
- Repository analysis: languages, frameworks, dependencies, configuration, test files/commands, build scripts, testing-gap heuristic.
- Static analysis: Python AST rules and complexity, Ruff integration, JavaScript/TypeScript rule engine; evidence lines, certainty labels, review statuses persisted across re-analysis.
- Rule-based pytest and Vitest generation; optional AI generation (Anthropic) with schema and syntax validation; review, edit, approve/reject, export.
- Execution-provider abstraction with `disabled`, `docker` sandbox and `local_trusted` (demo-only) providers; isolated runner image.
- Results with raw output, rule-based failure analysis, optional AI failure analysis; run comparison.
- Coverage via coverage.py and Vitest v8.
- Bug reports from findings, failures or manual entry; Markdown/JSON export.
- AI testing assistant with a grounded no-AI mode.
- PDF/HTML QA reports; analytics dashboard.
- Database-backed job queue with leases, retries and cancellation; Alembic migrations; Docker, Docker Compose and Render Blueprint; Windows/macOS start scripts.
