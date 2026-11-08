# Execution Security

TestPilot can execute tests against code imported from GitHub or uploaded as archives. **All such code is treated as untrusted**: a test file, a `conftest.py`, an imported module or a Vitest setup can run arbitrary code the moment the test runner loads it.

## Principles

1. The **API process never executes repository code.** It parses files (Python `ast`, Ruff) and stores metadata.
2. Execution happens only through an **`ExecutionProvider`**, invoked by the separate worker.
3. Only **approved** generated tests are written into the job workspace; unapproved proposals are rejected by the API (HTTP 422).
4. If no safe provider is available, runs are recorded as **`execution_unavailable`** — nothing is simulated.

## Providers

### `disabled` (default)
No code runs. Analysis, generation, review, bug reports and reports remain available. This is the configuration used on Render.

### `docker` — the sandbox provider
For each run the worker:

1. Copies the snapshot into `STORAGE_ROOT/runs/<id>/work` (same filters as import: no symlinks, size/file-count limits) and writes approved generated tests into `testpilot_generated/`.
2. Starts `testpilot-runner:latest` with:

| Control | Flag |
|---|---|
| No network | `--network none` |
| Immutable root filesystem | `--read-only` |
| Writable scratch only | `--tmpfs /tmp:rw,noexec,nosuid,size=64m` |
| No Linux capabilities | `--cap-drop ALL` |
| No privilege escalation (setuid) | `--security-opt no-new-privileges` |
| Unprivileged user | `--user 65534:65534` (nobody) |
| Process limit (fork bombs) | `--pids-limit 128` (`EXECUTION_PIDS_LIMIT`) |
| Memory limit, no swap | `--memory 512m --memory-swap 512m` (`EXECUTION_MEMORY_MB`) |
| CPU limit | `--cpus 1.0` (`EXECUTION_CPUS`) |
| File-descriptor limit | `--ulimit nofile=512:512` |
| Hard timeout | runner-internal timeout (`EXECUTION_TIMEOUT`) **and** worker-side kill at timeout + 30 s |
| Secrets | no environment variables are passed except `HOME=/tmp`; the image contains no application code or credentials |
| Host access | only `/work` (the per-run copy) and `/out` are mounted; **the Docker socket is never mounted** |
| Cleanup | `--rm`; the worker deletes `work/` after every run, including failed and errored runs (a hard crash of the worker process itself can leave a directory behind); only `out/` artefacts (junit, coverage, log) are retained |

3. Parses artefacts as untrusted input (10 MB XML cap, DOCTYPE/ENTITY rejected, 20 MB JSON cap, text truncated).

The runner image (`execution-runner/Dockerfile`) contains only Python 3.12 + pytest + coverage, and Node 22 + Vitest + `@vitest/coverage-v8`. Vitest is started with TestPilot's own config (`--configLoader runner`), so a project's `vite.config.*` — which could load arbitrary plugins — is **not** loaded.

### `local_trusted`
A subprocess with a scrubbed environment and **no isolation**. It refuses to run unless `ENVIRONMENT=development`, `ALLOW_LOCAL_TRUSTED_EXECUTION=true`, the project is the bundled demo, and the language is Python. Production configuration validation rejects it.

## Verified by automated tests

`backend/tests/test_execution_sandbox.py` (runs when Docker and the image are available; skipped — never reported as passed — otherwise) uploads a hostile project whose tests assert, *from inside the sandbox*, that:

* no environment variable containing `SECRET`, `TOKEN`, `API_KEY`, `DATABASE` or a canary value set in the worker is visible;
* the process runs as uid/euid 65534;
* a TCP connection to `1.1.1.1:53` fails;
* writes to `/opt/runner`, `/etc` and `/usr/local` fail;
* `/var/run/docker.sock` does not exist and no host paths are mounted;
* `NoNewPrivs` is 1 and the effective capability set is 0.

Additional tests: a 600-second `sleep` is stopped as `timed_out` in under 60 s; a fork bomb is contained by the PID limit; the canary never appears in the run log. Archive tests cover zip-slip, absolute paths, symlinks/hardlinks, decompression bombs and file-count limits.

## Known limitations — read before exposing execution publicly

* **Containers share the host kernel.** A kernel or container-runtime vulnerability could allow escape. For multi-tenant production use, run the worker on dedicated, disposable hosts, or implement a provider on gVisor (`--runtime=runsc`), Kata Containers or Firecracker microVMs.
* **Disk usage in `/work` is not quota-limited** (bind mounts have no per-container quota on most drivers). Snapshot size limits bound the input; a malicious test could still write large files until the timeout. Use a dedicated volume/filesystem with quotas for the runs directory.
* The worker needs access to the Docker daemon, which is root-equivalent on the worker host. Never run the worker on the same host as other sensitive services, and **never** run it inside a container with the host Docker socket mounted.
* No dependency installation (network is off). This is a deliberate trade-off.
* This design has **not been independently security-audited**. It must not be described as enterprise-grade sandboxing.

## Render

Render web services and workers are not suitable sandboxes for arbitrary code, and they do not provide a Docker daemon. The Blueprint therefore sets `EXECUTION_PROVIDER=disabled`. To offer execution in production, run the API and a `docker`-provider worker on infrastructure you control, sharing the same database **and** the same `STORAGE_ROOT` volume (snapshots are files on disk; object-storage support is on the roadmap), or implement an external sandbox provider.
