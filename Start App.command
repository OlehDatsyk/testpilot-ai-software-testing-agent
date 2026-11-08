#!/usr/bin/env bash
# TestPilot AI — macOS / Linux launcher. Double-click in Finder or run ./Start\ App.command
set -uo pipefail
cd "$(dirname "$0")"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
ok()  { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail(){ red "[error] $*"; echo "Startup did not complete. No data was deleted."; read -r -p "Press Enter to close…" _; exit 1; }

echo "=========================================="
echo "  TestPilot AI — local development start"
echo "=========================================="

# 1. Dependencies
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then PY="$c"; break; fi
done
[ -n "$PY" ] || fail "Python 3.11+ not found. Install it from https://www.python.org/downloads/ or 'brew install python@3.12'."
command -v node >/dev/null 2>&1 || fail "Node.js 20+ not found. Install it from https://nodejs.org/ or 'brew install node'."
command -v npm  >/dev/null 2>&1 || fail "npm not found. Reinstall Node.js."
ok "Python ($($PY --version)) and Node.js ($(node --version)) found."

# 2. Environment (never overwrites an existing .env)
OUT="$("$PY" scripts/prepare_env.py)" || fail "Environment configuration is invalid: $OUT"
echo "$OUT" | sed 's/^/    /'
EXEC="$(echo "$OUT" | tail -n1 | cut -d= -f2)"

# 3. Dependencies (installed only when missing)
if [ ! -x backend/.venv/bin/python ]; then
  echo "[..] Creating Python virtual environment…"
  "$PY" -m venv backend/.venv || fail "Could not create the virtual environment."
  backend/.venv/bin/python -m pip install --upgrade pip >/dev/null
  backend/.venv/bin/python -m pip install -r backend/requirements.txt || fail "Backend dependency installation failed."
fi
if [ ! -d frontend/node_modules ]; then
  echo "[..] Installing frontend dependencies…"
  (cd frontend && npm ci) || fail "Frontend dependency installation failed."
fi
ok "Dependencies installed."

# 4. Execution provider
if [ "$EXEC" = "docker" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    warn "EXECUTION_PROVIDER=docker but Docker is not installed — execution will report 'unavailable'. https://www.docker.com/products/docker-desktop/"
  elif ! docker info >/dev/null 2>&1; then
    warn "Docker is not running. Start Docker Desktop; until then execution reports 'unavailable'."
  else
    docker image inspect testpilot-runner:latest >/dev/null 2>&1 || {
      echo "[..] Building the isolated runner image (first run only)…"
      docker build -t testpilot-runner:latest execution-runner || warn "Runner image build failed; execution will report 'unavailable'."
    }
    ok "Docker sandbox ready."
  fi
else
  echo "[info] Test execution is '$EXEC'. Set EXECUTION_PROVIDER=docker in .env to run tests in the sandbox."
fi

# 5. Start services
mkdir -p backend/data/logs
PIDS=()
cleanup() { echo; echo "Stopping TestPilot…"; kill "${PIDS[@]}" 2>/dev/null; wait 2>/dev/null; echo "Stopped. Your data in backend/data is kept."; }
trap cleanup EXIT INT TERM
(cd backend && exec .venv/bin/python -m uvicorn app.main:app --port 8000) > backend/data/logs/api.log 2>&1 & PIDS+=($!)
(cd backend && exec .venv/bin/python -m app.worker) > backend/data/logs/worker.log 2>&1 & PIDS+=($!)
(cd frontend && exec npm run dev) > backend/data/logs/frontend.log 2>&1 & PIDS+=($!)

echo "[..] Waiting for the API…"
for i in $(seq 1 40); do
  curl -sf http://localhost:8000/health/ready >/dev/null 2>&1 && break
  if [ "$i" = 40 ]; then red "[error] API did not start. Last log lines:"; tail -n 20 backend/data/logs/api.log; exit 1; fi
  sleep 1
done
ok "TestPilot AI is running"
echo "    App       http://localhost:5173"
echo "    API docs  http://localhost:8000/api/docs"
echo "    Logs      backend/data/logs/"
command -v open >/dev/null 2>&1 && open http://localhost:5173
echo "Press Ctrl+C (or close this window) to stop."
wait
