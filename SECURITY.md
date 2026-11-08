# Security

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's *Report a vulnerability* (private security advisory) on this repository. Include steps to reproduce and affected versions. Only the latest release receives security fixes.

## Authentication & sessions

* Passwords: bcrypt (cost 12) over a SHA-256 pre-hash (avoids bcrypt's 72-byte truncation); minimum 10 characters with a letter and a digit.
* Access tokens: HS256 JWT signed with `SECRET_KEY`, 12 h expiry, carrying a per-user `token_version`; **logout increments the version and revokes all tokens**.
* Login timing is equalised for unknown accounts; generic "Invalid email or password".
* Tokens are sent as `Authorization: Bearer` (no cookies → no CSRF surface). The SPA stores only its own access token in `localStorage`.
* Production start-up refuses a default/short `SECRET_KEY`, wildcard CORS and the `local_trusted` execution provider.

## Authorisation

Every project-scoped endpoint resolves the project through one dependency that checks workspace membership; jobs, runs, results, findings, bugs, reports and conversations are validated against the project. Other users' resources return 404. Covered by `test_cross_user_isolation`.

## GitHub token protection

OAuth `state` is a signed, 10-minute, purpose-bound token (CSRF protection for the callback). Access tokens are encrypted with Fernet (key from `TOKEN_ENCRYPTION_KEY` or derived from `SECRET_KEY`), decrypted only in the worker/API when calling GitHub, never returned by any endpoint (tested), never logged (redaction filter for `gh*_`, `github_pat_`, bearer tokens, URL passwords, `password=`/`token=` patterns). Only `GET` requests are issued to GitHub.

## File upload & repository handling

Uploads are type- and size-checked; extraction happens in the worker with zip-slip, absolute path, link, decompression-bomb and file-count protections (`test_archives.py`). Snapshots are stored outside any web-served directory; the file-content endpoint resolves paths and rejects traversal. Uploaded archives are deleted after extraction. Deleting a project removes its snapshots and reports.

## Test execution isolation

See [EXECUTION_SECURITY.md](EXECUTION_SECURITY.md). Summary: API never executes repository code; only approved tests run; Docker sandbox with no network, non-root, read-only root FS, dropped capabilities, resource limits, timeout, no secrets; hostile-probe tests verify these properties. Container isolation is not equivalent to VM isolation and has not been independently audited.

## Database protection

Parameterised queries via SQLAlchemy ORM; no raw SQL built from input. Use a dedicated PostgreSQL user with rights only on the TestPilot database; on Render the Blueprint sets an empty `ipAllowList` (internal access only). Large artefacts are kept out of the database.

## HTTP hardening

Strict CORS allow-list (no credentials mode), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, generic 500 responses, Pydantic validation with length limits on all inputs, in-memory rate limiting on auth and AI endpoints. HTML reports are rendered with Jinja2 autoescaping; the frontend never uses `dangerouslySetInnerHTML` (assistant Markdown is rendered to React elements).

## Secrets in the repository

`.env` and `.env.*` (except `.env.example`) are git-ignored, as are local databases, storage, logs and generated artefacts. `.env.example` contains placeholders only. Frontend `VITE_*` variables are public by design — never place secrets there.

## Known gaps

In-memory rate limiting does not span multiple API instances; no MFA; no account lockout beyond rate limiting; no email verification; JWT revocation is per-user (not per-device).
