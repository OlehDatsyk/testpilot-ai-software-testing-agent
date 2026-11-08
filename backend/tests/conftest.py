import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="testpilot-tests-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "STORAGE_ROOT": str(_TMP / "storage"),
    "SECRET_KEY": "test-secret-key-that-is-long-enough-123456",
    "EXECUTION_PROVIDER": "disabled",
    "AI_PROVIDER": "none",
    "AUTO_CREATE_TABLES": "true",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.provider import set_provider  # noqa: E402
from app.database.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.worker import run_pending_once  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    set_provider(None)
    yield
    set_provider(None)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client, email="alice@example.com", name="Alice", password="CorrectHorse42"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client):
    return register(client)


@pytest.fixture
def demo_project(client, auth):
    r = client.post("/api/projects/demo", headers=auth)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run_pending_once()
    return pid


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)
