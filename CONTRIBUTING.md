# Contributing

Thanks for helping improve TestPilot AI!

## Workflow

1. **Fork** the repository and clone your fork.
2. Create a branch from `main`: `git checkout -b feat/short-description` (or `fix/…`, `docs/…`).
3. Set up the environment ([INSTRUCTION.md](INSTRUCTION.md) §3) and install dev dependencies: `pip install -r backend/requirements-dev.txt`.
4. Make focused changes with tests.
5. Run the checks below, then open a **pull request** against `main` describing what changed, why, and how it was tested.

## Checks (must pass)

```bash
cd backend && python -m ruff check app tests && python -m pytest
```

```bash
cd frontend && npx tsc --noEmit -p . && npm test && npm run build
```

Docker-sandbox tests run automatically when Docker and `testpilot-runner:latest` are available, and are skipped (not passed) otherwise — mention in your PR whether they ran. Schema changes need an Alembic migration (`alembic revision --autogenerate -m "…"`), reviewed by hand.

## Code style

* Python: type hints, small modules, Ruff (`backend/pyproject.toml`), line length 130.
* TypeScript: `strict` mode, functional React components, Tailwind utility classes using the theme tokens in `src/index.css`, shared primitives from `components/ui.tsx`.
* User-facing text must never overstate results: distinguish measured vs suggested, never show unexecuted tests as passed, never invent coverage or locations.

## Security expectations

* Never commit secrets, real tokens, private repository content or customer reports.
* Never execute repository code in the API process; new execution paths must go through an `ExecutionProvider` and be covered by isolation tests.
* Treat all repository content and runner artefacts as untrusted input.
* Report vulnerabilities privately (see [SECURITY.md](SECURITY.md)).

## Demo project

`demo-project/` contains **deliberate** defects used by tests and screenshots. Do not "fix" them.
