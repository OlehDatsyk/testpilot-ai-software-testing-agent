import threading

import pytest

from app.core.config import Settings
from app.execution.providers import LocalTrustedProvider, get_execution_provider


def test_production_requires_strong_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(environment="production", secret_key="short").validate_for_runtime()
    Settings(environment="production", secret_key="x" * 40, cors_origins="https://app.example.com").validate_for_runtime()


def test_production_rejects_local_trusted_and_wildcard_cors():
    with pytest.raises(RuntimeError, match="local_trusted"):
        Settings(environment="production", secret_key="x" * 40, execution_provider="local_trusted").validate_for_runtime()
    with pytest.raises(RuntimeError, match="CORS"):
        Settings(environment="production", secret_key="x" * 40, cors_origins="*").validate_for_runtime()


def test_embedded_worker_requires_execution_disabled():
    with pytest.raises(RuntimeError, match="RUN_WORKER_IN_API"):
        Settings(run_worker_in_api=True, execution_provider="docker").validate_for_runtime()
    Settings(run_worker_in_api=True, execution_provider="disabled").validate_for_runtime()


def test_render_style_database_url_normalised():
    assert Settings(database_url="postgres://u:p@h:5432/d").database_url == "postgresql+psycopg://u:p@h:5432/d"


def test_local_trusted_refuses_non_demo_code(monkeypatch):
    from pathlib import Path

    from app.core.config import settings
    from app.execution.providers import ExecutionSpec
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "allow_local_trusted_execution", True)
    spec = ExecutionSpec("k", "python", Path("."), Path("."), True, trusted_demo=False)
    ok, reason = LocalTrustedProvider().availability(spec)
    assert not ok and "demo" in reason
    monkeypatch.setattr(settings, "allow_local_trusted_execution", False)
    assert LocalTrustedProvider().availability(None)[0] is False


def test_default_provider_is_disabled():
    assert get_execution_provider().name == "disabled"


def test_embedded_worker_loop_processes_jobs_and_stops(client, auth):
    from app.worker import run_loop
    pid = client.post("/api/projects/demo", headers=auth).json()["id"]
    stop = threading.Event()
    t = threading.Thread(target=run_loop, args=(stop, "test-embedded"), daemon=True)
    t.start()
    import time
    for _ in range(60):
        if client.get(f"/api/projects/{pid}", headers=auth).json()["status"] == "ready":
            break
        time.sleep(0.5)
    stop.set()
    t.join(timeout=10)
    assert not t.is_alive()
    assert client.get(f"/api/projects/{pid}", headers=auth).json()["status"] == "ready"
