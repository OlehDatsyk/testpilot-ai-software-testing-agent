import io
import tarfile
import zipfile

import pytest

from app.services.archive import ArchiveError, extract_archive

LIMITS = {"max_total_bytes": 1_000_000, "max_files": 50}


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_valid_zip_strips_single_root_and_skips_vendor(tmp_path):
    data = _zip({"proj/app.py": b"x = 1\n", "proj/node_modules/lib.js": b"evil", "proj/.git/config": b"x"})
    res = extract_archive(data, tmp_path / "out", **LIMITS)
    assert (tmp_path / "out" / "app.py").read_text() == "x = 1\n"
    assert not (tmp_path / "out" / "node_modules").exists()
    assert res.file_count == 1


@pytest.mark.parametrize("name", ["../evil.py", "a/../../evil.py", "/abs/evil.py", "C:/win/evil.py", "..\\evil.py"])
def test_zip_slip_rejected(tmp_path, name):
    with pytest.raises(ArchiveError):
        extract_archive(_zip({name: b"pwned"}), tmp_path / "out", **LIMITS)
    assert not (tmp_path / "evil.py").exists()


def test_decompression_bomb_rejected(tmp_path):
    data = _zip({"big.txt": b"0" * 1_500_000})  # compresses to a few KB
    assert len(data) < 20_000
    with pytest.raises(ArchiveError, match="maximum extracted size"):
        extract_archive(data, tmp_path / "out", max_total_bytes=1_000_000, max_files=50, max_file_bytes=5_000_000)


def test_too_many_files(tmp_path):
    with pytest.raises(ArchiveError):
        extract_archive(_zip({f"f{i}.py": b"" for i in range(60)}), tmp_path / "out", **LIMITS)


def test_tar_symlink_and_hardlink_not_materialised(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("repo/link")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(info)
        hl = tarfile.TarInfo("repo/hard")
        hl.type, hl.linkname = tarfile.LNKTYPE, "/etc/shadow"
        t.addfile(hl)
        good = tarfile.TarInfo("repo/ok.py")
        good.size = 4
        t.addfile(good, io.BytesIO(b"x=1\n"))
    res = extract_archive(buf.getvalue(), tmp_path / "out", **LIMITS)
    assert (tmp_path / "out" / "ok.py").exists()
    assert not (tmp_path / "out" / "link").exists() and not (tmp_path / "out" / "hard").exists()
    assert len(res.skipped) == 2 and all("non-regular" in s["reason"] for s in res.skipped)


def test_tar_traversal_rejected(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("../../escape.py")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ArchiveError):
        extract_archive(buf.getvalue(), tmp_path / "out", **LIMITS)


def test_garbage_rejected(tmp_path):
    with pytest.raises(ArchiveError):
        extract_archive(b"this is not an archive", tmp_path / "out", **LIMITS)


def test_upload_endpoint_rejects_wrong_type_and_malicious(client, auth):
    r = client.post("/api/projects/upload", headers=auth, data={"name": "x"},
                    files={"archive": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/projects/upload", headers=auth, data={"name": "evil"},
                    files={"archive": ("evil.zip", _zip({"../../evil.py": b"x"}), "application/zip")})
    assert r.status_code == 201
    pid = r.json()["id"]
    from app.worker import run_pending_once
    run_pending_once()
    p = client.get(f"/api/projects/{pid}", headers=auth).json()
    assert p["status"] == "error" and p["latest_snapshot_id"] is None
    jobs = client.get(f"/api/projects/{pid}/jobs", headers=auth).json()
    assert jobs[0]["status"] == "failed" and "traversal" in jobs[0]["error"].lower()


def test_upload_valid_archive_runs_analysis(client, auth):
    src = _zip({"pkg/calc.py": b"def div(a, b):\n    if b == 0:\n        raise ValueError('b')\n    return a / b\n",
                "pkg/package.json": b'{"name":"x","scripts":{"test":"vitest"},"devDependencies":{"vitest":"1"}}'})
    r = client.post("/api/projects/upload", headers=auth, data={"name": "calc"},
                    files={"archive": ("calc.zip", src, "application/zip")})
    pid = r.json()["id"]
    from app.worker import run_pending_once
    run_pending_once()
    a = client.get(f"/api/projects/{pid}/analysis", headers=auth).json()
    assert a["summary"]["supported_languages"] == ["Python"]
    assert "Vitest" in a["summary"]["frameworks"]
    assert a["summary"]["test_commands"] == ["npm run test"]
