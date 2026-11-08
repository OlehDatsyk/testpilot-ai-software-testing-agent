@echo off
setlocal EnableExtensions EnableDelayedExpansion
title TestPilot AI - launcher
cd /d "%~dp0"

echo.
echo  ==========================================
echo    TestPilot AI - local development start
echo  ==========================================
echo.

rem ---- 1. Dependencies ------------------------------------------------------
set "PY="
where py >nul 2>nul && (py -3 --version >nul 2>nul && set "PY=py -3")
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python 3.11+ was not found. Install it from https://www.python.org/downloads/ and tick "Add to PATH".
  goto :fail
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || (
  echo [ERROR] Python 3.11 or newer is required.
  %PY% --version
  goto :fail
)
where node >nul 2>nul || ( echo [ERROR] Node.js 20+ was not found. Install it from https://nodejs.org/ & goto :fail )
where npm >nul 2>nul || ( echo [ERROR] npm was not found. Reinstall Node.js. & goto :fail )
echo [ok] Python and Node.js found.

rem ---- 2. Environment configuration (never overwrites an existing .env) ----
for /f "usebackq delims=" %%L in (`%PY% scripts\prepare_env.py`) do (
  echo     %%L
  set "LAST=%%L"
)
if errorlevel 1 goto :fail
for /f "tokens=2 delims==" %%V in ("!LAST!") do set "EXEC=%%V"

rem ---- 3. Install / update dependencies (only when missing) ---------------
if not exist "backend\.venv\Scripts\python.exe" (
  echo [..] Creating Python virtual environment...
  %PY% -m venv backend\.venv || ( echo [ERROR] Could not create the virtual environment. & goto :fail )
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || ( echo [ERROR] Backend dependency installation failed. & goto :fail )
)
if not exist "frontend\node_modules" (
  echo [..] Installing frontend dependencies...
  pushd frontend
  call npm ci || ( popd & echo [ERROR] Frontend dependency installation failed. & goto :fail )
  popd
)
echo [ok] Dependencies installed.

rem ---- 4. Execution provider ------------------------------------------------
if /i "!EXEC!"=="docker" (
  where docker >nul 2>nul || (
    echo [WARN] EXECUTION_PROVIDER=docker but Docker is not installed. Test execution will report "unavailable".
    echo        Install Docker Desktop: https://www.docker.com/products/docker-desktop/
    goto :start
  )
  docker info >nul 2>nul || (
    echo [WARN] Docker is installed but not running. Start Docker Desktop; until then execution reports "unavailable".
    goto :start
  )
  docker image inspect testpilot-runner:latest >nul 2>nul || (
    echo [..] Building the isolated runner image ^(first run only^)...
    docker build -t testpilot-runner:latest execution-runner || echo [WARN] Runner image build failed; execution will report "unavailable".
  )
  echo [ok] Docker sandbox ready.
) else (
  echo [info] Test execution is "!EXEC!". Analysis, generation and reports work; set EXECUTION_PROVIDER=docker in .env to run tests.
)

:start
rem ---- 5. Start services ----------------------------------------------------
echo [..] Starting API, worker and frontend in separate windows...
start "TestPilot API" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "TestPilot Worker" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m app.worker"
start "TestPilot Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo [..] Waiting for the API...
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://localhost:8000/health/ready -TimeoutSec 2) | Out-Null; exit 0 } catch { exit 1 }" && goto :ready
if !tries! geq 40 (
  echo [ERROR] The API did not become ready. Check the "TestPilot API" window for errors.
  goto :fail
)
timeout /t 1 >nul
goto :wait

:ready
echo.
echo  TestPilot AI is running:
echo    App       http://localhost:5173
echo    API docs  http://localhost:8000/api/docs
echo  Close the three service windows to stop. Your data in backend\data is kept.
start "" http://localhost:5173
pause
exit /b 0

:fail
echo.
echo Startup did not complete. No data was deleted.
pause
exit /b 1
