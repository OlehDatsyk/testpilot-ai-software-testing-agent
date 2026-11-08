# API Documentation

Base URL (local): `http://localhost:8000`. Interactive docs: `/api/docs` (Swagger) and `/api/redoc`. The full OpenAPI schema generated from the code is in [`docs/openapi.json`](docs/openapi.json); this page lists every implemented endpoint (68).

## Conventions

* **Authentication:** `Authorization: Bearer <access_token>` from `/api/auth/register` or `/api/auth/login`. Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 12 h) and are revoked by `/api/auth/logout`.
* **Authorisation:** every `/api/projects/{project_id}/…` route verifies the caller belongs to the project's workspace. Foreign or missing resources return **404** (existence is not leaked).
* **Errors:** `{"error": {"status": <int>, "message": "<text>", "details": [{"field": "...", "message": "..."}]}}` (`details` on 422 validation errors). Unhandled errors return a generic 500 without internals.
* **Pagination:** list endpoints that return `Page` accept `page` (≥1) and `page_size` (1–200) and respond `{"items": [...], "total", "page", "page_size"}`.
* **Long-running work** returns **202** with a `Job` (`id`, `job_type`, `status`, `error`, `result`, `attempts`, …). Poll `GET /api/jobs/{id}`. Statuses: `queued`, `preparing`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `execution_unavailable`, `infrastructure_error`.
* **Rate limits:** auth endpoints `AUTH_RATE_LIMIT_PER_MINUTE` per IP (default 20); AI-backed endpoints 30/min per IP; AI provider calls `AI_MAX_REQUESTS_PER_HOUR`. Exceeding returns **429** with `Retry-After`.

## System
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | – | Liveness (no dependency checks) |
| GET | `/health/ready` | – | Readiness: database reachable → 200, else 503 |
| GET | `/api/system/capabilities` | – | Version, AI/GitHub configured flags, execution provider availability, queue depth, limits (no secrets) |

## Auth & workspaces
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | `{email, name, password}` → `{access_token, user}` (201). Password ≥10 chars with a letter and digit; 409 if email exists |
| POST | `/api/auth/login` | `{email, password}` → token; 401 on bad credentials |
| POST | `/api/auth/logout` | Revokes all tokens of the user (204) |
| GET | `/api/auth/me` | User, workspaces, GitHub connection summary (never the token) |
| GET / POST | `/api/workspaces` | List / create workspaces |
| PATCH | `/api/workspaces/{workspace_id}` | Rename (owner only) |

## GitHub
| Method | Path | Description |
|---|---|---|
| GET | `/api/github/status` | OAuth configured? connected? login, scopes |
| GET | `/api/github/oauth/start?include_private=bool` | Returns `authorize_url` with a signed `state` (503 if OAuth not configured) |
| GET | `/api/github/oauth/callback?code&state` | GitHub redirect target; stores encrypted token; redirects to `FRONTEND_URL/settings?github=…` |
| DELETE | `/api/github/connection` | Disconnect |
| GET | `/api/github/repos` | Repositories visible to the connected account |
| GET | `/api/github/lookup?repository=` | Repo metadata + branches (public, or private if connected). 400 invalid input, 404, 429 rate limit |
| GET | `/api/github/projects/{project_id}/tree?ref=` | Latest commit + recursive file listing |

## Projects & jobs
| Method | Path | Description |
|---|---|---|
| GET | `/api/projects?q&status&language&page&page_size` | Search/filter projects |
| POST | `/api/projects` | Manual project `{name, description, repository_url}` |
| POST | `/api/projects/github` | `{repository, branch?, name?}` → project + import job |
| POST | `/api/projects/upload` | multipart `name`, `description`, `archive` (.zip/.tar.gz, ≤ `MAX_REPOSITORY_SIZE_MB`; 413/415) |
| POST | `/api/projects/demo` | Create the labelled demo project (403 if demo mode disabled) |
| GET / PATCH / DELETE | `/api/projects/{project_id}` | Read / rename / delete (409 while jobs are active) |
| POST | `/api/projects/{project_id}/import` | Re-import (GitHub branch or demo) → Job |
| POST | `/api/projects/{project_id}/analyse` | Analyse latest snapshot → Job |
| GET | `/api/projects/{project_id}/snapshots` | Snapshot history |
| GET | `/api/projects/{project_id}/files` | Files in latest snapshot |
| GET | `/api/projects/{project_id}/files/content?path=` | Text content (≤256 KB; traversal-safe) |
| GET | `/api/projects/{project_id}/jobs?limit` | Job history |
| GET | `/api/jobs/{job_id}` | Job status |
| POST | `/api/jobs/{job_id}/cancel` | Cancel queued job or request cancellation of a running one (409 if finished) |

## Analysis & generation
| Method | Path | Description |
|---|---|---|
| GET | `/api/projects/{project_id}/analysis` | Latest analysis (summary, analysers that ran) or `null` |
| GET | `/api/projects/{project_id}/analyses` | History with findings-by-severity |
| GET | `/api/projects/{project_id}/findings?severity&status&category&q&analysis_id` | Findings (Page) |
| PATCH | `/api/projects/{project_id}/findings/{finding_id}` | `{status: open|accepted|false_positive|resolved}` (persists across re-analysis by fingerprint) |
| POST | `/api/projects/{project_id}/generate` | `{files?, use_ai?, focus?}` → Job (400 if not analysed) |
| GET | `/api/projects/{project_id}/generated-tests?status&language&category` | Proposals (Page) |
| PATCH | `/api/projects/{project_id}/generated-tests/{test_id}` | `{code?, status?}`; editing code resets approval; approving an invalid test → 422 |
| POST | `/api/projects/{project_id}/generated-tests/review` | Bulk `{ids, status}` → `{updated, skipped_invalid}` |
| GET | `/api/projects/{project_id}/generated-tests/export` | Zip of approved tests (404 if none) |

## Test runs, results & coverage
| Method | Path | Description |
|---|---|---|
| GET | `/api/projects/{project_id}/execution/status` | Provider and per-language availability with reason |
| POST | `/api/projects/{project_id}/runs` | `{language: Python|JavaScript|TypeScript, include_existing, generated_test_ids}` → Run (202). 422 if a test is not approved or wrong language |
| GET | `/api/projects/{project_id}/runs?status` | Runs (Page) incl. coverage summary |
| GET | `/api/projects/{project_id}/runs/{run_id}` | Run |
| GET | `/api/projects/{project_id}/runs/{run_id}/results?status` | Per-test results (raw message/traceback, rule analysis, AI analysis) |
| GET | `/api/projects/{project_id}/runs/{run_id}/log` | Raw runner output (text/plain) |
| POST | `/api/projects/{project_id}/results/{result_id}/ai-analysis` | AI failure analysis (503 if no AI provider) |
| GET | `/api/projects/{project_id}/runs/compare/{base_id}/{head_id}` | Regressions, fixes, new/removed tests, coverage delta (same tool only), findings delta |
| GET | `/api/projects/{project_id}/coverage` | Coverage history |
| GET | `/api/projects/{project_id}/coverage/latest` | Latest coverage report or `null` |
| GET | `/api/projects/{project_id}/coverage/untested` | Source files absent from the latest coverage report |

## Bug reports
| Method | Path | Description |
|---|---|---|
| GET / POST | `/api/projects/{project_id}/bugs` | List (q, status, severity; Page) / create manually |
| POST | `/api/projects/{project_id}/bugs/from-source` | `{source_type: finding|test_result, source_id}` — prefilled from evidence only |
| GET / PATCH / DELETE | `/api/projects/{project_id}/bugs/{bug_id}` | Read / edit (incl. status, notes) / delete |
| GET | `/api/projects/{project_id}/bugs/{bug_id}/export?format=markdown|json` | Export |

## Assistant & reports
| Method | Path | Description |
|---|---|---|
| GET | `/api/projects/{project_id}/conversations` | The caller's conversations |
| GET | `/api/projects/{project_id}/conversations/{conv_id}/messages` | Messages |
| POST | `/api/projects/{project_id}/assistant` | `{message, conversation_id?}` → `{conversation_id, message}`; `message.provider` is `ai:<model>` or `grounded-rules` |
| GET / POST | `/api/projects/{project_id}/reports` | List / create `{title?, run_id?}` → Job |
| GET | `/api/projects/{project_id}/reports/{report_id}/download?format=pdf|html` | File (409 if not ready, 410 if storage was reset) |

## Analytics
| Method | Path | Description |
|---|---|---|
| GET | `/api/analytics/overview?project_id` | Dashboard counters, findings by severity, recent runs and activity |
| GET | `/api/analytics/trends?days&project_id` | Daily generated/executed/passed/failed, coverage series, average duration, findings by status, activity by project |

## Example

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"YourPassword1"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8000/api/projects/demo -H "Authorization: Bearer $TOKEN"
```
