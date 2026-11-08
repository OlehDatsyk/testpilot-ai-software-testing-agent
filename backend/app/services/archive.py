"""Safe extraction of untrusted project archives (.zip / .tar.gz).

Defences:
* path traversal ("zip slip"): absolute paths, drive letters and ``..`` are rejected
* symlinks, hard links and device files are never materialised
* decompression bombs: extracted bytes are counted while streaming and the
  extraction aborts once ``max_total_bytes`` is exceeded
* file-count limit
* dependency / VCS / build directories are skipped
* individual large files are skipped (recorded, not extracted)

Nothing extracted here is ever executed by the API process.
"""
from __future__ import annotations

import io
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", "coverage", "htmlcov", ".idea", ".vscode",
    "site-packages", ".eggs",
}
CHUNK = 64 * 1024


class ArchiveError(ValueError):
    """Raised for archives that are malformed, malicious or exceed limits."""


@dataclass
class ExtractionResult:
    root: Path
    file_count: int = 0
    total_bytes: int = 0
    skipped: list[dict] = field(default_factory=list)


def _safe_relpath(name: str) -> PurePosixPath | None:
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ArchiveError(f"Absolute path in archive rejected: {name[:200]}")
    parts = [p for p in PurePosixPath(name).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveError(f"Path traversal in archive rejected: {name[:200]}")
    if not parts:
        return None
    return PurePosixPath(*parts)


def _strip_common_root(names: list[PurePosixPath]) -> int:
    """Return 1 if all entries share a single top-level directory (GitHub tarballs)."""
    tops = {n.parts[0] for n in names if n.parts}
    if len(tops) == 1 and all(len(n.parts) > 1 for n in names if n.parts):
        return 1
    return 0


def _should_skip_dir(rel: PurePosixPath) -> bool:
    return any(part in SKIP_DIRS for part in rel.parts[:-1])


def _write_stream(src, dest: Path, budget: list[int], max_file_bytes: int) -> int:
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            written += len(chunk)
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise ArchiveError("Archive exceeds the maximum extracted size (possible decompression bomb)")
            if written > max_file_bytes:
                raise _FileTooLarge()
            out.write(chunk)
    return written


class _FileTooLarge(Exception):
    pass


def extract_archive(
    data: bytes,
    dest: Path,
    *,
    max_total_bytes: int,
    max_files: int,
    max_file_bytes: int = 2 * 1024 * 1024,
) -> ExtractionResult:
    dest.mkdir(parents=True, exist_ok=True)
    result = ExtractionResult(root=dest)
    budget = [max_total_bytes]

    if zipfile.is_zipfile(io.BytesIO(data)):
        _extract_zip(data, dest, result, budget, max_files, max_file_bytes)
    else:
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        except tarfile.TarError as exc:
            raise ArchiveError("Unsupported or corrupt archive (expected .zip or .tar.gz)") from exc
        with tf:
            _extract_tar(tf, dest, result, budget, max_files, max_file_bytes)
    return result


def _extract_zip(data, dest, result, budget, max_files, max_file_bytes):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Corrupt zip archive") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > max_files * 4:
            raise ArchiveError("Archive contains too many entries")
        rels = []
        for info in infos:
            rel = _safe_relpath(info.filename)
            rels.append(rel)
        strip = _strip_common_root([r for r in rels if r is not None])
        for info, rel in zip(infos, rels):
            if rel is None or info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode and mode not in (stat.S_IFREG,):
                result.skipped.append({"path": str(rel), "reason": "non-regular file (symlink/device) ignored"})
                continue
            _materialise(rel, strip, lambda i=info: zf.open(i), info.file_size, dest, result, budget, max_files, max_file_bytes)


def _extract_tar(tf, dest, result, budget, max_files, max_file_bytes):
    members = []
    for m in tf:
        members.append(m)
        if len(members) > max_files * 4:
            raise ArchiveError("Archive contains too many entries")
    rels = [_safe_relpath(m.name) for m in members]
    strip = _strip_common_root([r for r, m in zip(rels, members) if r is not None and m.name != "pax_global_header"])
    for m, rel in zip(members, rels):
        if rel is None or m.isdir() or m.name == "pax_global_header":
            continue
        if not m.isfile():
            result.skipped.append({"path": str(rel), "reason": "non-regular file (symlink/link/device) ignored"})
            continue
        _materialise(rel, strip, lambda mm=m: tf.extractfile(mm), m.size, dest, result, budget, max_files, max_file_bytes)


def _materialise(rel, strip, opener, declared_size, dest, result, budget, max_files, max_file_bytes):
    rel = PurePosixPath(*rel.parts[strip:]) if strip and len(rel.parts) > strip else rel
    if _should_skip_dir(rel):
        return
    if declared_size > max_file_bytes:
        result.skipped.append({"path": str(rel), "reason": f"file larger than {max_file_bytes // 1024} KB"})
        return
    if result.file_count >= max_files:
        raise ArchiveError(f"Archive exceeds the maximum of {max_files} files")
    target = (dest / Path(*rel.parts)).resolve()
    if not str(target).startswith(str(dest.resolve())):
        raise ArchiveError("Path traversal in archive rejected")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = opener()
    if src is None:
        return
    try:
        with src:
            written = _write_stream(src, target, budget, max_file_bytes)
    except _FileTooLarge:
        target.unlink(missing_ok=True)
        result.skipped.append({"path": str(rel), "reason": f"file larger than {max_file_bytes // 1024} KB"})
        return
    result.file_count += 1
    result.total_bytes += written


def copy_tree(src: Path, dest: Path, *, max_files: int, max_total_bytes: int, max_file_bytes: int = 2 * 1024 * 1024) -> ExtractionResult:
    """Copy a trusted local directory (the bundled demo project) applying the same filters."""
    result = ExtractionResult(root=dest)
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        rel = PurePosixPath(path.relative_to(src).as_posix())
        if path.is_symlink() or not path.is_file() or _should_skip_dir(rel):
            continue
        size = path.stat().st_size
        if size > max_file_bytes:
            result.skipped.append({"path": str(rel), "reason": "file too large"})
            continue
        if result.file_count >= max_files or result.total_bytes + size > max_total_bytes:
            raise ArchiveError("Project exceeds snapshot limits")
        target = dest / Path(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        result.file_count += 1
        result.total_bytes += size
    return result
