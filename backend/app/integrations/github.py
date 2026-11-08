"""GitHub REST API client (read-only usage).

TestPilot only ever issues GET requests to GitHub plus the OAuth token
exchange. It never pushes, comments or modifies repositories.

Scopes:
* public repositories: no scope at all (``read:user`` only to show the login)
* private repositories: OAuth Apps have no read-only scope for repository
  contents, so ``repo`` is requested *only* when the user opts in. TestPilot
  still performs read operations only. A GitHub App with "Contents: read-only"
  is the recommended production alternative (see roadmap).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings

REPO_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:)?([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,200}$")
PUBLIC_SCOPES = "read:user"
PRIVATE_SCOPES = "read:user repo"


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class GitHubRateLimited(GitHubError):
    pass


def parse_repo(value: str) -> str:
    m = REPO_RE.match(value.strip())
    if not m:
        raise GitHubError("Not a valid GitHub repository URL or owner/name")
    owner, name = m.group(1), m.group(2)
    if name in (".", ".."):
        raise GitHubError("Invalid repository name")
    return f"{owner}/{name}"


def validate_branch(ref: str) -> str:
    if not BRANCH_RE.match(ref) or ".." in ref:
        raise GitHubError("Invalid branch name")
    return ref


@dataclass
class GitHubClient:
    token: str | None = None
    timeout: float = 30.0

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": "TestPilot-AI"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _check(self, r: httpx.Response) -> None:
        if r.status_code in (403, 429) and (r.headers.get("x-ratelimit-remaining") == "0" or r.status_code == 429):
            reset = r.headers.get("x-ratelimit-reset")
            wait = max(0, int(reset) - int(time.time())) if reset and reset.isdigit() else None
            raise GitHubRateLimited(f"GitHub API rate limit exceeded{f'; resets in {wait}s' if wait is not None else ''}", r.status_code)
        if r.status_code == 401:
            raise GitHubError("GitHub rejected the access token; reconnect GitHub", 401)
        if r.status_code == 404:
            raise GitHubError("Repository or branch not found (or not accessible with the current authorisation)", 404)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error (HTTP {r.status_code})", r.status_code)

    def get(self, path: str, params: dict | None = None):
        with httpx.Client(base_url=settings.github_api_url, timeout=self.timeout, headers=self._headers()) as c:
            r = c.get(path, params=params)
        self._check(r)
        return r.json()

    def repo(self, full_name: str) -> dict:
        d = self.get(f"/repos/{full_name}")
        return {
            "full_name": d["full_name"], "description": d.get("description") or "", "private": d.get("private", False),
            "default_branch": d.get("default_branch"), "html_url": d.get("html_url"), "language": d.get("language"),
            "stars": d.get("stargazers_count"), "size_kb": d.get("size"), "pushed_at": d.get("pushed_at"),
        }

    def branches(self, full_name: str) -> list[dict]:
        data = self.get(f"/repos/{full_name}/branches", {"per_page": 100})
        return [{"name": b["name"], "sha": b["commit"]["sha"]} for b in data]

    def latest_commit(self, full_name: str, ref: str) -> dict:
        d = self.get(f"/repos/{full_name}/commits/{ref}")
        return {"sha": d["sha"], "message": (d.get("commit", {}).get("message") or "")[:300],
                "author": (d.get("commit", {}).get("author") or {}).get("name"),
                "date": (d.get("commit", {}).get("author") or {}).get("date")}

    def tree(self, full_name: str, ref: str) -> dict:
        d = self.get(f"/repos/{full_name}/git/trees/{ref}", {"recursive": "1"})
        entries = [{"path": e["path"], "type": e["type"], "size": e.get("size")} for e in d.get("tree", [])[:5000]]
        return {"truncated": bool(d.get("truncated")), "entries": entries}

    def user_repos(self) -> list[dict]:
        data = self.get("/user/repos", {"per_page": 100, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"})
        return [{"full_name": d["full_name"], "private": d["private"], "default_branch": d["default_branch"],
                 "description": d.get("description") or "", "language": d.get("language")} for d in data]

    def user(self) -> dict:
        return self.get("/user")

    def download_tarball(self, full_name: str, ref: str, max_bytes: int) -> bytes:
        """Stream the repository tarball, aborting once ``max_bytes`` is exceeded."""
        url = f"{settings.github_api_url}/repos/{full_name}/tarball/{ref}"
        buf = bytearray()
        with httpx.Client(timeout=120, headers=self._headers(), follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                if r.status_code >= 400:
                    r.read()
                    self._check(r)
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise GitHubError(f"Repository archive exceeds the {max_bytes // (1024 * 1024)} MB limit")
        return bytes(buf)


def oauth_authorize_url(state: str, include_private: bool) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": PRIVATE_SCOPES if include_private else PUBLIC_SCOPES,
        "state": state,
        "allow_signup": "false",
    }
    return "https://github.com/login/oauth/authorize?" + urlencode(params)


def exchange_code(code: str) -> tuple[str, str]:
    with httpx.Client(timeout=30) as c:
        r = c.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data={
            "client_id": settings.github_client_id, "client_secret": settings.github_client_secret,
            "code": code, "redirect_uri": settings.github_redirect_uri,
        })
    if r.status_code != 200:
        raise GitHubError("GitHub token exchange failed")
    data = r.json()
    if "access_token" not in data:
        raise GitHubError(f"GitHub token exchange failed: {data.get('error', 'unknown error')}")
    return data["access_token"], data.get("scope", "")
