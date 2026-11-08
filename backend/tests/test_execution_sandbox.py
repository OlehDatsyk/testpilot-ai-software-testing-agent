"""Real execution through the Docker sandbox provider.

Skipped automatically when Docker or the runner image is unavailable — they are
never reported as passed in that case.
"""
import io
import os
import zipfile

import pytest

from app.core.config import settings
from app.execution.providers import DockerSandboxProvider
from app.worker import run_pending_once

_ok, _reason = DockerSandboxProvider().availability()
pytestmark = pytest.mark.skipif(not _ok, reason=f"Docker sandbox unavailable: {_reason}")


@pytest.fixture(autouse=True)
def docker_provider(monkeypatch):
    monkeypatch.setattr(settings, "execution_provider", "docker")
    monkeypatch.setattr(settings, "execution_timeout", 120)


def _run(client, auth, pid, body):
    r = client.post(f"/api/projects/{pid}/runs", json=body, headers=auth)
    assert r.status_code == 202, r.text
    run_pending_once()
    run = client.get(f"/api/projects/{pid}/runs/{r.json()['id']}", headers=auth).json()
    results = client.get(f"/api/projects/{pid}/runs/{run['id']}/results", headers=auth).json()
    return run, results


def test_demo_python_existing_and_generated(client, auth, demo_project):
    pid = demo_project
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    gen = client.get(f"/api/projects/{pid}/generated-tests", params={"language": "Python", "page_size": 200},
                     headers=auth).json()["items"]
    ids = [t["id"] for t in gen]
    client.post(f"/api/projects/{pid}/generated-tests/review", json={"ids": ids, "status": "approved"}, headers=auth)
    run, results = _run(client, auth, pid, {"language": "Python", "include_existing": True, "generated_test_ids": ids})
    by_name = {r["name"]: r for r in results}
    assert run["status"] == "partially_passed", run
    assert run["total"] == len(results) and run["passed"] + run["failed"] + run["errors"] + run["skipped"] == run["total"]
    # Deliberate defect 1: boundary bug found by the existing test
    bulk = by_name["test_bulk_price_applies_at_100_units"]
    assert bulk["status"] == "failed" and "80.0" in bulk["traceback"]
    # Deliberate defect 2: generated edge-case test exposes ZeroDivisionError
    edge = by_name["test_average_price_handles_empty_list_prices"]
    assert edge["status"] == "failed" and edge["rule_analysis"]["exception_type"] == "ZeroDivisionError"
    assert edge["generated_test_id"] in ids
    # Docstring-derived test passes
    assert by_name["test_apply_discount_docstring_example_1"]["status"] == "passed"
    # Coverage measured by coverage.py
    assert run["coverage"] and 0 < run["coverage"]["line_percent"] <= 100
    cov = client.get(f"/api/projects/{pid}/coverage/latest", headers=auth).json()
    assert cov["tool"].startswith("coverage.py") and any(f["path"] == "inventory/pricing.py" for f in cov["files"])
    log = client.get(f"/api/projects/{pid}/runs/{run['id']}/log", headers=auth).text
    assert "pytest" in log


def test_demo_javascript_with_vitest(client, auth, demo_project):
    pid = demo_project
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    gen = client.get(f"/api/projects/{pid}/generated-tests", params={"language": "JavaScript"}, headers=auth).json()["items"]
    ids = [t["id"] for t in gen]
    client.post(f"/api/projects/{pid}/generated-tests/review", json={"ids": ids, "status": "approved"}, headers=auth)
    run, results = _run(client, auth, pid, {"language": "JavaScript", "include_existing": True, "generated_test_ids": ids})
    assert run["total"] >= 5, (run, results)
    assert run["status"] == "passed", [r for r in results if r["status"] != "passed"]
    assert run["coverage"] and run["coverage"]["tool"] == "vitest (v8)"


PROBES = r'''
import os, socket, pathlib, subprocess

def test_no_application_secrets_in_environment():
    leaked = [k for k in os.environ if any(s in k.upper() for s in ("SECRET", "TOKEN", "API_KEY", "DATABASE", "CANARY"))]
    assert leaked == []

def test_runs_as_unprivileged_user():
    assert os.getuid() == 65534 and os.geteuid() == 65534

def test_network_is_disabled():
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect(("1.1.1.1", 53))
        connected = True
    except OSError:
        connected = False
    finally:
        s.close()
    assert not connected

def test_root_filesystem_is_read_only():
    for target in ("/opt/runner/pwned", "/etc/pwned", "/usr/local/pwned"):
        try:
            pathlib.Path(target).write_text("x")
            ok = True
        except OSError:
            ok = False
        assert not ok, target

def test_no_docker_socket_and_no_host_storage():
    assert not os.path.exists("/var/run/docker.sock")
    mounted = {line.split()[1] for line in open("/proc/mounts")}
    assert "/work" in mounted and "/out" in mounted
    assert not any(m.startswith("/host") for m in mounted)

def test_cannot_escalate_privileges():
    status = open("/proc/self/status").read()
    assert "NoNewPrivs:\t1" in status
    cap_eff = [l for l in status.splitlines() if l.startswith("CapEff")][0].split()[1]
    assert int(cap_eff, 16) == 0
'''


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def test_untrusted_code_cannot_reach_secrets_network_or_host(client, auth, monkeypatch):
    monkeypatch.setenv("TESTPILOT_CANARY_SECRET", "canary-value-should-never-leak")
    data = _zip({"probe/test_isolation.py": PROBES})
    r = client.post("/api/projects/upload", headers=auth, data={"name": "isolation probe"},
                    files={"archive": ("probe.zip", data, "application/zip")})
    pid = r.json()["id"]
    run_pending_once()
    run, results = _run(client, auth, pid, {"language": "Python", "include_existing": True})
    failing = {x["name"]: x["message"] for x in results if x["status"] != "passed"}
    assert run["status"] == "passed" and run["total"] == 6, failing
    assert "canary-value" not in client.get(f"/api/projects/{pid}/runs/{run['id']}/log", headers=auth).text
    assert os.environ.get("TESTPILOT_CANARY_SECRET")  # the worker had it; the sandbox did not


def test_timeout_is_enforced(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "execution_timeout", 8)
    data = _zip({"slow/test_slow.py": "import time\n\ndef test_forever():\n    time.sleep(600)\n"})
    pid = client.post("/api/projects/upload", headers=auth, data={"name": "slow"},
                      files={"archive": ("slow.zip", data, "application/zip")}).json()["id"]
    run_pending_once()
    run, _ = _run(client, auth, pid, {"language": "Python", "include_existing": True})
    assert run["status"] == "timed_out"
    assert run["duration_seconds"] < 60


def test_fork_bomb_is_contained(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "execution_timeout", 20)
    code = ("import os\n\ndef test_fork():\n    pids = []\n    try:\n        for _ in range(1000):\n"
            "            pid = os.fork()\n            if pid == 0:\n                import time; time.sleep(30); os._exit(0)\n"
            "            pids.append(pid)\n    except OSError:\n        pass\n    assert len(pids) < 200\n")
    pid = client.post("/api/projects/upload", headers=auth, data={"name": "forks"},
                      files={"archive": ("f.zip", _zip({"f/test_fork.py": code}), "application/zip")}).json()["id"]
    run_pending_once()
    run, results = _run(client, auth, pid, {"language": "Python", "include_existing": True})
    # Either the pids limit stops forking (test passes) or the job hits the timeout — never unbounded.
    assert run["status"] in ("passed", "timed_out"), (run, results)
