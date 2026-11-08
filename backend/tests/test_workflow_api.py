"""End-to-end API workflow with the execution provider DISABLED (default)."""
from app.models import TestResult, TestRun
from app.worker import run_pending_once


def _approve_some(client, auth, pid, n=3, language="Python"):
    tests = client.get(f"/api/projects/{pid}/generated-tests", params={"language": language, "page_size": 200},
                       headers=auth).json()["items"]
    ids = [t["id"] for t in tests[:n]]
    r = client.post(f"/api/projects/{pid}/generated-tests/review", json={"ids": ids, "status": "approved"}, headers=auth)
    assert r.json()["updated"] == n
    return ids


def test_demo_import_analysis_generation(client, auth, demo_project):
    pid = demo_project
    p = client.get(f"/api/projects/{pid}", headers=auth).json()
    assert p["is_demo"] and p["status"] == "ready" and p["languages"] == ["Python", "JavaScript"]
    a = client.get(f"/api/projects/{pid}/analysis", headers=auth).json()
    assert a["tools"]["ruff"]["status"] == "ran"
    assert a["tools"]["eslint"]["status"] == "not_implemented"
    f = client.get(f"/api/projects/{pid}/findings", params={"page_size": 200}, headers=auth).json()
    assert f["total"] > 5
    rules = {x["rule_id"] for x in f["items"]}
    assert "RUFF-E722" in rules and "PY001" not in rules  # de-duplicated in favour of Ruff
    # Generation
    j = client.post(f"/api/projects/{pid}/generate", json={}, headers=auth).json()
    assert j["status"] == "queued"
    run_pending_once()
    job = client.get(f"/api/jobs/{j['id']}", headers=auth).json()
    assert job["status"] == "succeeded" and job["result"]["created"] > 5
    gen = client.get(f"/api/projects/{pid}/generated-tests", params={"page_size": 200}, headers=auth).json()
    assert all(t["status"] == "proposed" for t in gen["items"])
    assert {t["language"] for t in gen["items"]} == {"Python", "JavaScript"}
    # Re-generating does not duplicate
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    assert client.get(f"/api/projects/{pid}/generated-tests", headers=auth).json()["total"] == gen["total"]


def test_unapproved_tests_cannot_run(client, auth, demo_project):
    pid = demo_project
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    t = client.get(f"/api/projects/{pid}/generated-tests", headers=auth).json()["items"][0]
    r = client.post(f"/api/projects/{pid}/runs", json={"language": "Python", "generated_test_ids": [t["id"]]}, headers=auth)
    assert r.status_code == 422 and "approved" in r.json()["error"]["message"]


def test_edited_test_requires_reapproval(client, auth, demo_project):
    pid = demo_project
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    [tid] = _approve_some(client, auth, pid, 1)
    r = client.patch(f"/api/projects/{pid}/generated-tests/{tid}", json={"code": "def test_x():\n    assert True\n"},
                     headers=auth).json()
    assert r["status"] == "proposed" and r["validation"]["edited_by_user"]
    bad = client.patch(f"/api/projects/{pid}/generated-tests/{tid}", json={"code": "def test_x(:\n"}, headers=auth).json()
    assert bad["validation"]["syntax_ok"] is False
    r = client.patch(f"/api/projects/{pid}/generated-tests/{tid}", json={"status": "approved"}, headers=auth)
    assert r.status_code == 422


def test_execution_disabled_is_reported_honestly(client, auth, demo_project):
    pid = demo_project
    client.post(f"/api/projects/{pid}/generate", json={}, headers=auth)
    run_pending_once()
    ids = _approve_some(client, auth, pid, 2)
    r = client.post(f"/api/projects/{pid}/runs", json={"language": "Python", "generated_test_ids": ids}, headers=auth)
    assert r.status_code == 202
    run_id = r.json()["id"]
    run_pending_once()
    run = client.get(f"/api/projects/{pid}/runs/{run_id}", headers=auth).json()
    assert run["status"] == "execution_unavailable"
    assert run["passed"] == 0 and run["total"] == 0 and run["coverage"] is None
    assert client.get(f"/api/projects/{pid}/runs/{run_id}/results", headers=auth).json() == []
    assert client.get(f"/api/projects/{pid}/coverage/latest", headers=auth).json() is None
    ov = client.get("/api/analytics/overview", headers=auth).json()
    assert ov["tests_executed"] == 0 and ov["passed"] == 0


def test_cancel_queued_run(client, auth, demo_project):
    pid = demo_project
    r = client.post(f"/api/projects/{pid}/runs", json={"language": "Python", "include_existing": True}, headers=auth).json()
    c = client.post(f"/api/jobs/{r['job_id']}/cancel", headers=auth).json()
    assert c["status"] == "cancelled"
    assert client.get(f"/api/projects/{pid}/runs/{r['id']}", headers=auth).json()["status"] == "cancelled"
    run_pending_once()
    assert client.get(f"/api/projects/{pid}/runs/{r['id']}", headers=auth).json()["status"] == "cancelled"


def test_finding_review_persists_across_reanalysis(client, auth, demo_project):
    pid = demo_project
    f = client.get(f"/api/projects/{pid}/findings", headers=auth).json()["items"][0]
    client.patch(f"/api/projects/{pid}/findings/{f['id']}", json={"status": "false_positive"}, headers=auth)
    client.post(f"/api/projects/{pid}/analyse", headers=auth)
    run_pending_once()
    items = client.get(f"/api/projects/{pid}/findings", params={"page_size": 200}, headers=auth).json()["items"]
    same = [x for x in items if x["rule_id"] == f["rule_id"] and x["file_path"] == f["file_path"] and x["line"] == f["line"]]
    assert same and same[0]["status"] == "false_positive" and same[0]["id"] != f["id"]


def _fake_run_with_failure(pid):
    from app.database.session import SessionLocal
    from app.execution.failure_analysis import analyse_failure
    from app.models import Project
    with SessionLocal() as db:
        p = db.get(Project, pid)
        run = TestRun(project_id=pid, snapshot_id=p.latest_snapshot_id, language="Python", framework="pytest",
                      provider="docker", status="partially_passed", total=2, passed=1, failed=1)
        db.add(run)
        db.flush()
        tb = ('tests/test_pricing.py:24: in test_bulk_price_applies_at_100_units\n    assert bulk_price(1.0, 100) == 80.0\n'
              'E   AssertionError: assert 100.0 == 80.0')
        db.add(TestResult(run_id=run.id, node_id="tests.test_pricing::test_bulk", name="test_bulk", status="failed",
                          file_path="tests/test_pricing.py", message="AssertionError: assert 100.0 == 80.0", traceback=tb,
                          rule_analysis=analyse_failure("AssertionError: assert 100.0 == 80.0", tb, "python")))
        db.add(TestResult(run_id=run.id, node_id="tests.test_pricing::test_ok", name="test_ok", status="passed"))
        db.commit()
        return run.id


def test_bug_reports_from_evidence(client, auth, demo_project):
    pid = demo_project
    f = client.get(f"/api/projects/{pid}/findings", headers=auth).json()["items"][0]
    b = client.post(f"/api/projects/{pid}/bugs/from-source", json={"source_type": "finding", "source_id": f["id"]},
                    headers=auth).json()
    assert b["file_path"] == f["file_path"] and b["line"] == f["line"]
    assert b["reproduction_steps"] is None and b["expected_behaviour"] is None  # never invented
    run_id = _fake_run_with_failure(pid)
    res = client.get(f"/api/projects/{pid}/runs/{run_id}/results", headers=auth).json()
    assert res[0]["status"] == "failed" and res[0]["rule_analysis"]["exception_type"] == "AssertionError"
    b2 = client.post(f"/api/projects/{pid}/bugs/from-source", json={"source_type": "test_result", "source_id": res[0]["id"]},
                     headers=auth).json()
    assert "assert 100.0 == 80.0" in b2["actual_behaviour"] and b2["expected_behaviour"] is None
    upd = client.patch(f"/api/projects/{pid}/bugs/{b2['id']}", json={"status": "resolved", "notes": "fixed"}, headers=auth).json()
    assert upd["status"] == "resolved"
    md = client.get(f"/api/projects/{pid}/bugs/{b['id']}/export", headers=auth).text
    assert "_Not available — no evidence recorded._" in md
    lst = client.get(f"/api/projects/{pid}/bugs", params={"status": "resolved"}, headers=auth).json()
    assert lst["total"] == 1
    # comparison
    run2 = _fake_run_with_failure(pid)
    cmp = client.get(f"/api/projects/{pid}/runs/compare/{run_id}/{run2}", headers=auth).json()
    assert cmp["comparable"] and cmp["regressions"] == [] and cmp["common_tests"] == 2


def test_report_generation(client, auth, demo_project):
    pid = demo_project
    _fake_run_with_failure(pid)
    j = client.post(f"/api/projects/{pid}/reports", json={}, headers=auth).json()
    run_pending_once()
    assert client.get(f"/api/jobs/{j['id']}", headers=auth).json()["status"] == "succeeded"
    rep = client.get(f"/api/projects/{pid}/reports", headers=auth).json()[0]
    assert rep["status"] == "ready"
    pdf = client.get(f"/api/projects/{pid}/reports/{rep['id']}/download", params={"format": "pdf"}, headers=auth)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    html = client.get(f"/api/projects/{pid}/reports/{rep['id']}/download", params={"format": "html"}, headers=auth).text
    assert "MEASURED" in html and "SUGGESTED" in html and "DEMO PROJECT" in html
    assert "test-secret-key" not in html


def test_assistant_grounded_without_ai(client, auth, demo_project):
    pid = demo_project
    r = client.post(f"/api/projects/{pid}/assistant", json={"message": "Summarise the latest test run"}, headers=auth).json()
    assert r["message"]["provider"] == "grounded-rules"
    assert "No test run has been executed" in r["message"]["content"]
    _fake_run_with_failure(pid)
    r2 = client.post(f"/api/projects/{pid}/assistant", json={"message": "Why did the test fail?",
                                                            "conversation_id": r["conversation_id"]}, headers=auth).json()
    assert "test_bulk" in r2["message"]["content"] and "AssertionError" in r2["message"]["content"]
    msgs = client.get(f"/api/projects/{pid}/conversations/{r['conversation_id']}/messages", headers=auth).json()
    assert len(msgs) == 4


def test_ai_analysis_unavailable_without_provider(client, auth, demo_project):
    pid = demo_project
    run_id = _fake_run_with_failure(pid)
    res = client.get(f"/api/projects/{pid}/runs/{run_id}/results", headers=auth).json()[0]
    r = client.post(f"/api/projects/{pid}/results/{res['id']}/ai-analysis", headers=auth)
    assert r.status_code == 503


def test_delete_project(client, auth, demo_project):
    assert client.delete(f"/api/projects/{demo_project}", headers=auth).status_code == 204
    assert client.get(f"/api/projects/{demo_project}", headers=auth).status_code == 404
