import io
import logging
import tarfile

import httpx
import pytest

from app.ai.provider import AIProvider, AIUnavailable, set_provider
from app.ai.schemas import AIAssistantAnswer, AITestSuggestions
from app.core.logging import RedactingFilter, redact
from app.core.security import decrypt_secret, encrypt_secret
from app.execution.failure_analysis import analyse_failure
from app.execution.results import ArtefactError, parse_junit, parse_python_coverage
from app.integrations.github import GitHubError, parse_repo, validate_branch
from app.worker import run_pending_once

# --- GitHub ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    ("octo/hello", "octo/hello"), ("https://github.com/octo/hello", "octo/hello"),
    ("https://github.com/octo/hello.git", "octo/hello"), ("git@github.com:octo/hello.git", "octo/hello"),
])
def test_parse_repo_valid(value, expected):
    assert parse_repo(value) == expected


@pytest.mark.parametrize("value", ["", "octo", "https://evil.com/octo/hello", "octo/../x", "octo/hello/extra", "a b/c"])
def test_parse_repo_invalid(value):
    with pytest.raises(GitHubError):
        parse_repo(value)


def test_validate_branch():
    assert validate_branch("feature/x-1") == "feature/x-1"
    for bad in ("a..b", "x;rm -rf", ""):
        with pytest.raises(GitHubError):
            validate_branch(bad)


def _tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in {"octo-hello-abc123/lib/maths.py": b"def add(a: int, b: int) -> int:\n    return a + b\n",
                           "octo-hello-abc123/tests/test_maths.py": b"from lib.maths import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_github(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        p = request.url.path
        if p == "/repos/octo/hello":
            return httpx.Response(200, json={"full_name": "octo/hello", "description": "demo", "private": False,
                                             "default_branch": "main", "html_url": "https://github.com/octo/hello"})
        if p == "/repos/octo/hello/branches":
            return httpx.Response(200, json=[{"name": "main", "commit": {"sha": "abc123"}}])
        if p == "/repos/octo/hello/commits/main":
            return httpx.Response(200, json={"sha": "abc123", "commit": {"message": "init", "author": {"name": "o"}}})
        if p == "/repos/octo/hello/tarball/abc123":
            return httpx.Response(200, content=_tarball())
        if p == "/repos/octo/limited":
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"})
        return httpx.Response(404)

    real = httpx.Client

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "Client", factory)
    return calls


def test_github_lookup_and_import(client, auth, fake_github):
    info = client.get("/api/github/lookup", params={"repository": "https://github.com/octo/hello"}, headers=auth).json()
    assert info["default_branch"] == "main" and info["branches"][0]["name"] == "main"
    p = client.post("/api/projects/github", json={"repository": "octo/hello"}, headers=auth).json()
    assert p["github_full_name"] == "octo/hello" and p["status"] == "importing"
    run_pending_once()
    snaps = client.get(f"/api/projects/{p['id']}/snapshots", headers=auth).json()
    assert snaps[0]["commit_sha"] == "abc123" and snaps[0]["file_count"] == 2
    a = client.get(f"/api/projects/{p['id']}/analysis", headers=auth).json()
    assert a["summary"]["totals"]["test_files"] == 1
    # Only GET requests were made to GitHub — nothing is ever written to the repository.
    assert {c.method for c in fake_github} == {"GET"}


def test_github_errors_mapped(client, auth, fake_github):
    assert client.get("/api/github/lookup", params={"repository": "octo/missing"}, headers=auth).status_code == 404
    assert client.get("/api/github/lookup", params={"repository": "octo/limited"}, headers=auth).status_code == 429
    assert client.get("/api/github/lookup", params={"repository": "not a repo"}, headers=auth).status_code == 400


def test_oauth_not_configured(client, auth):
    assert client.get("/api/github/oauth/start", headers=auth).status_code == 503
    assert client.get("/api/github/status", headers=auth).json()["oauth_configured"] is False


def test_oauth_callback_rejects_forged_state(client):
    r = client.get("/api/github/oauth/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
    assert r.status_code in (302, 307) and "invalid_state" in r.headers["location"]


def test_token_encryption_roundtrip():
    enc = encrypt_secret("gho_abcdefghijklmnopqrstuvwxyz123456")
    assert "gho_" not in enc and decrypt_secret(enc) == "gho_abcdefghijklmnopqrstuvwxyz123456"
    assert decrypt_secret("tampered") is None


def test_github_token_never_returned(client, auth):
    from app.database.session import SessionLocal
    from app.models import GitHubConnection
    with SessionLocal() as db:
        db.add(GitHubConnection(user_id=1, github_login="alice-gh", encrypted_token=encrypt_secret("gho_SECRETTOKEN1234567890abcd"),
                                scopes="read:user"))
        db.commit()
    for path in ("/api/auth/me", "/api/github/status"):
        body = client.get(path, headers=auth).text
        assert "alice-gh" in body and "gho_" not in body and "encrypted" not in body


# --- logging ---------------------------------------------------------------------------------

def test_log_redaction(caplog):
    out = redact("using ghp_abcdefghijklmnopqrstuvwxyz0123 now")
    assert "abcdefghijklmnop" not in out and "REDACTED" in out
    assert "s3cret" not in redact("postgresql://user:s3cret@db/x")
    assert "sk-ant-api03" not in redact("key sk-ant-api03-abcdefghijklmnop")
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "Authorization: Bearer %s", ("eyJabc.def.ghi",), None)
    RedactingFilter().filter(rec)
    assert "eyJabc" not in rec.getMessage()


# --- result parsing -----------------------------------------------------------------------------

def test_junit_parsing(tmp_path):
    (tmp_path / "j.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.test_a" name="test_ok" time="0.01"/>'
        '<testcase classname="tests.test_a" name="test_bad" time="0.02"><failure message="assert 1 == 2">tb here</failure></testcase>'
        '<testcase classname="tests.test_a" name="test_skip"><skipped message="nope"/></testcase>'
        '<testcase classname="tests.test_a" name="test_err"><error message="boom">trace</error></testcase></testsuite></testsuites>')
    res = {r.name: r for r in parse_junit(tmp_path / "j.xml")}
    assert [res[n].status for n in ("test_ok", "test_bad", "test_skip", "test_err")] == ["passed", "failed", "skipped", "error"]
    assert res["test_bad"].message == "assert 1 == 2" and res["test_bad"].file_path == "tests/test_a.py"


def test_junit_rejects_entities_and_missing(tmp_path):
    (tmp_path / "j.xml").write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite/>')
    with pytest.raises(ArtefactError):
        parse_junit(tmp_path / "j.xml")
    with pytest.raises(ArtefactError):
        parse_junit(tmp_path / "missing.xml")


def test_coverage_parsing(tmp_path):
    (tmp_path / "c.json").write_text('{"meta":{"version":"7.6"},"totals":{"covered_lines":8,"num_statements":10,'
                                     '"num_branches":4,"covered_branches":1},"files":{"/work/pkg/a.py":{"summary":'
                                     '{"percent_covered":80.0,"num_statements":10,"covered_lines":8},"missing_lines":[3,4]}}}')
    c = parse_python_coverage(tmp_path / "c.json")
    assert c["line_percent"] == 80.0 and c["branch_percent"] == 25.0 and c["function_percent"] is None
    assert c["files"][0]["path"] == "pkg/a.py" and c["files"][0]["missing_lines"] == [3, 4]
    assert parse_python_coverage(tmp_path / "none.json") is None


def test_failure_analysis_rules():
    tb = ('Traceback:\n  File "/work/inventory/pricing.py", line 26, in average_price\n    return sum(prices) / len(prices)\n'
          'E   ZeroDivisionError: division by zero')
    a = analyse_failure("ZeroDivisionError: division by zero", tb, "python")
    assert a["exception_type"] == "ZeroDivisionError" and a["location"] == {"file": "inventory/pricing.py", "line": 26}
    assert a["kind"] == "rule-based-suggestion"
    assert analyse_failure("Failed: DID NOT RAISE <class 'ValueError'>", None, "python")["exception_type"] == "Failed: DID NOT RAISE"
    unknown = analyse_failure("weird", "weird", "python")
    assert unknown["exception_type"] is None and unknown["location"] is None


# --- AI provider (fake) ---------------------------------------------------------------------------

class FakeAI(AIProvider):
    name = "fake"

    def __init__(self, tests=None, fail=False):
        self.tests, self.fail, self.prompts = tests or [], fail, []

    @property
    def available(self):
        return True

    @property
    def label(self):
        return "ai:fake-model"

    def structured(self, *, system, prompt, schema, max_tokens=8000):
        self.prompts.append(prompt)
        if self.fail:
            raise AIUnavailable("provider down")
        if schema is AITestSuggestions:
            return AITestSuggestions(tests=self.tests)
        if schema is AIAssistantAnswer:
            return AIAssistantAnswer(answer="From context: 0 runs.", used_sources=["latest_run"], information_missing=True)
        raise AssertionError(schema)


def test_ai_generation_validated(client, auth, demo_project):
    good = {"name": "test_bulk_boundary", "description": "d", "target": "bulk_price", "category": "boundary",
            "expected_behaviour": "100 units get discount", "rationale": "docstring",
            "code": "from inventory.pricing import bulk_price\n\ndef test_bulk_boundary():\n    assert bulk_price(1.0, 100) == 80.0\n"}
    bad = {**good, "name": "test_broken", "code": "def test_broken(:\n"}
    evil = {**good, "name": "test_evil", "code": "def test_evil():\n    eval('1')\n"}
    fake = FakeAI(tests=[good, bad, evil])
    set_provider(fake)
    client.post(f"/api/projects/{demo_project}/generate", json={"use_ai": True, "files": ["inventory/pricing.py"]}, headers=auth)
    run_pending_once()
    items = client.get(f"/api/projects/{demo_project}/generated-tests", params={"page_size": 200}, headers=auth).json()["items"]
    ai = [t for t in items if t["generator"] == "ai:fake-model"]
    assert [t["name"] for t in ai] == ["test_bulk_boundary"]  # invalid & forbidden outputs discarded
    assert ai[0]["rationale"].startswith("AI suggestion") and ai[0]["status"] == "proposed"
    assert "inventory/pricing.py" in fake.prompts[0] and "def bulk_price" in fake.prompts[0]


def test_ai_generation_failure_falls_back(client, auth, demo_project):
    set_provider(FakeAI(fail=True))
    j = client.post(f"/api/projects/{demo_project}/generate", json={"use_ai": True}, headers=auth).json()
    run_pending_once()
    job = client.get(f"/api/jobs/{j['id']}", headers=auth).json()
    assert job["status"] == "succeeded" and job["result"]["created"] > 0 and job["result"]["ai_messages"]


def test_assistant_uses_ai_with_grounded_context(client, auth, demo_project):
    fake = FakeAI()
    set_provider(fake)
    r = client.post(f"/api/projects/{demo_project}/assistant", json={"message": "Explain the architecture"}, headers=auth).json()
    assert r["message"]["provider"] == "ai:fake-model" and r["message"]["sources"] == ["latest_run"]
    assert "inventory/pricing.py" in fake.prompts[0] and "test-secret-key" not in fake.prompts[0]


def test_assistant_ai_failure_falls_back(client, auth, demo_project):
    set_provider(FakeAI(fail=True))
    r = client.post(f"/api/projects/{demo_project}/assistant", json={"message": "list open findings"}, headers=auth).json()
    assert r["message"]["provider"] == "grounded-rules" and "AI provider unavailable" in r["message"]["content"]
