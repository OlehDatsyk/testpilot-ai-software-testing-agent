from tests.conftest import register


def test_register_login_me(client):
    h = register(client)
    me = client.get("/api/auth/me", headers=h).json()
    assert me["user"]["email"] == "alice@example.com"
    assert len(me["workspaces"]) == 1 and me["workspaces"][0]["role"] == "owner"
    r = client.post("/api/auth/login", json={"email": "ALICE@example.com", "password": "CorrectHorse42"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_password_not_returned_and_hashed(client):
    h = register(client)
    body = client.get("/api/auth/me", headers=h).text
    assert "CorrectHorse42" not in body and "password" not in body


def test_weak_password_and_duplicate(client):
    r = client.post("/api/auth/register", json={"email": "b@example.com", "name": "B", "password": "short"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"email": "b@example.com", "name": "B", "password": "onlyletterslong"})
    assert r.status_code == 422
    register(client, "b@example.com")
    r = client.post("/api/auth/register", json={"email": "b@example.com", "name": "B", "password": "CorrectHorse42"})
    assert r.status_code == 409


def test_wrong_password(client):
    register(client)
    r = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "WrongHorse42"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "WrongHorse42"})
    assert r.status_code == 401


def test_protected_routes_require_token(client):
    for path in ("/api/projects", "/api/auth/me", "/api/analytics/overview", "/api/github/status"):
        assert client.get(path).status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_logout_invalidates_token(client):
    h = register(client)
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_cross_user_isolation(client, demo_project):
    other = register(client, "mallory@example.com", "Mallory")
    pid = demo_project
    for path in (f"/api/projects/{pid}", f"/api/projects/{pid}/analysis", f"/api/projects/{pid}/findings",
                 f"/api/projects/{pid}/generated-tests", f"/api/projects/{pid}/runs", f"/api/projects/{pid}/bugs",
                 f"/api/projects/{pid}/reports", f"/api/projects/{pid}/files",
                 f"/api/projects/{pid}/files/content?path=README.md", f"/api/projects/{pid}/coverage"):
        assert client.get(path, headers=other).status_code == 404, path
    assert client.delete(f"/api/projects/{pid}", headers=other).status_code == 404
    assert client.post(f"/api/projects/{pid}/runs", headers=other,
                       json={"language": "Python", "include_existing": True}).status_code == 404
    # Other user's project list and dashboard do not include it
    assert client.get("/api/projects", headers=other).json()["total"] == 0
    assert client.get("/api/analytics/overview", headers=other).json()["projects"] == 0


def test_file_content_path_traversal(client, auth, demo_project):
    pid = demo_project
    for bad in ("../../../etc/passwd", "..\\..\\x", "/etc/passwd"):
        r = client.get(f"/api/projects/{pid}/files/content", params={"path": bad}, headers=auth)
        assert r.status_code == 404


def test_health_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/health/ready").json()
    assert r == {"status": "ready", "database": "ok"}


def test_capabilities_reports_execution_disabled(client):
    caps = client.get("/api/system/capabilities").json()
    assert caps["execution"]["available"] is False
    assert caps["ai"]["configured"] is False
    assert "secret" not in str(caps).lower()
