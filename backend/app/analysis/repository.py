"""Repository structure analysis.

Works on an extracted snapshot directory. Only reads files (never imports or
executes them). Every reported fact is derived from a file that was actually
read; files that were skipped are reported as skipped.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

LANG_BY_EXT = {
    ".py": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
}
OTHER_LANG_BY_EXT = {
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".kt": "Kotlin",
    ".c": "C", ".cpp": "C++", ".h": "C/C++ header", ".swift": "Swift", ".html": "HTML", ".css": "CSS",
    ".scss": "SCSS", ".sh": "Shell", ".sql": "SQL",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".whl", ".so", ".dll",
    ".exe", ".bin", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wav", ".pyc", ".lock", ".db", ".sqlite",
}
CONFIG_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini",
    "mypy.ini", "ruff.toml", ".ruff.toml", "Pipfile", "poetry.lock", "package.json", "tsconfig.json",
    "vite.config.ts", "vite.config.js", "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js",
    "playwright.config.ts", "playwright.config.js", ".eslintrc", ".eslintrc.js", ".eslintrc.json", "eslint.config.js",
    "eslint.config.mjs", "Dockerfile", "docker-compose.yml", "Makefile", ".coveragerc",
}

PY_FRAMEWORKS = {
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask", "pytest": "pytest", "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic", "numpy": "NumPy", "pandas": "pandas", "requests": "requests", "celery": "Celery",
    "unittest": "unittest",
}
JS_FRAMEWORKS = {
    "react": "React", "vue": "Vue", "svelte": "Svelte", "next": "Next.js", "express": "Express", "vite": "Vite",
    "vitest": "Vitest", "jest": "Jest", "@playwright/test": "Playwright", "typescript": "TypeScript compiler",
    "eslint": "ESLint", "@angular/core": "Angular", "mocha": "Mocha", "nestjs": "NestJS", "@nestjs/core": "NestJS",
}


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")
    if name.endswith(".py"):
        return name.startswith("test_") or name.endswith("_test.py") or (name == "conftest.py")
    if re.search(r"\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$", name):
        return True
    return "__tests__" in parts and Path(name).suffix in LANG_BY_EXT


@dataclass
class FileEntry:
    path: str
    size: int
    language: str | None
    is_test: bool
    parsed: bool


@dataclass
class RepoScan:
    root: Path
    files: list[FileEntry] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    def source_files(self, language: str | None = None) -> list[FileEntry]:
        return [f for f in self.files if f.language in LANG_BY_EXT.values() and not f.is_test and f.parsed
                and (language is None or f.language == language)]

    def test_files(self) -> list[FileEntry]:
        return [f for f in self.files if f.is_test]


def scan_repository(root: Path, max_file_bytes: int) -> RepoScan:
    scan = RepoScan(root=root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        ext = path.suffix.lower()
        size = path.stat().st_size
        if ext in BINARY_EXT:
            scan.skipped.append({"path": rel, "reason": "binary or lock file"})
            continue
        lang = LANG_BY_EXT.get(ext) or OTHER_LANG_BY_EXT.get(ext)
        parsed = size <= max_file_bytes
        if not parsed:
            scan.skipped.append({"path": rel, "reason": f"larger than {max_file_bytes // 1024} KB, not parsed"})
        scan.files.append(FileEntry(rel, size, lang, is_test_file(rel), parsed))
    return scan


def read_text(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _parse_requirements(text: str) -> list[str]:
    deps = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip()
        if name:
            deps.append(line if len(line) < 120 else name)
    return deps


def inspect_python_config(root: Path, files: set[str]) -> dict:
    out: dict = {"dependencies": [], "dev_dependencies": [], "test_commands": [], "config_files": []}
    for req in sorted(f for f in files if re.fullmatch(r"(.*/)?requirements[\w\-]*\.txt", f)):
        text = read_text(root, req)
        if text is not None:
            target = "dev_dependencies" if "dev" in req or "test" in req else "dependencies"
            out[target].extend(_parse_requirements(text))
            out["config_files"].append(req)
    if "pyproject.toml" in files:
        text = read_text(root, "pyproject.toml")
        out["config_files"].append("pyproject.toml")
        if text:
            try:
                data = tomllib.loads(text)
                proj = data.get("project", {})
                out["package_name"] = proj.get("name")
                out["dependencies"].extend(proj.get("dependencies", []) or [])
                for group in (proj.get("optional-dependencies") or {}).values():
                    out["dev_dependencies"].extend(group)
                poetry = data.get("tool", {}).get("poetry", {})
                out["dependencies"].extend(k for k in (poetry.get("dependencies") or {}) if k != "python")
                if "pytest" in data.get("tool", {}):
                    out["pytest_config"] = "pyproject.toml [tool.pytest]"
            except tomllib.TOMLDecodeError:
                out["pyproject_error"] = "pyproject.toml could not be parsed"
    for name in ("setup.py", "setup.cfg", "pytest.ini", "tox.ini", "mypy.ini", "ruff.toml", ".coveragerc"):
        if name in files:
            out["config_files"].append(name)
    if "pytest.ini" in files:
        out["pytest_config"] = "pytest.ini"
    return out


def inspect_package_json(root: Path, files: set[str]) -> dict:
    out: dict = {"dependencies": [], "dev_dependencies": [], "scripts": {}, "test_commands": [], "config_files": []}
    if "package.json" not in files:
        return out
    text = read_text(root, "package.json")
    out["config_files"].append("package.json")
    if not text:
        return out
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        out["package_json_error"] = "package.json is not valid JSON"
        return out
    out["package_name"] = data.get("name")
    out["dependencies"] = sorted((data.get("dependencies") or {}).keys())
    out["dev_dependencies"] = sorted((data.get("devDependencies") or {}).keys())
    scripts = data.get("scripts") or {}
    out["scripts"] = {k: str(v)[:200] for k, v in scripts.items()}
    out["test_commands"] = [f"npm run {k}" for k in scripts if k == "test" or k.startswith("test:")]
    out["module_type"] = data.get("type", "commonjs")
    return out


def detect_python_frameworks(root: Path, scan: RepoScan, deps: list[str]) -> set[str]:
    found: set[str] = set()
    dep_names = {re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0].lower() for d in deps}
    for key, label in PY_FRAMEWORKS.items():
        if key in dep_names:
            found.add(label)
    # Imports in source and test files (read, not executed)
    import_re = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", re.M)
    for f in scan.files:
        if f.language == "Python" and f.parsed:
            text = read_text(root, f.path) or ""
            for mod in import_re.findall(text):
                if mod.lower() in PY_FRAMEWORKS:
                    found.add(PY_FRAMEWORKS[mod.lower()])
    return found


def detect_js_frameworks(pkg: dict, files: set[str]) -> set[str]:
    found: set[str] = set()
    for dep in pkg.get("dependencies", []) + pkg.get("dev_dependencies", []):
        if dep in JS_FRAMEWORKS:
            found.add(JS_FRAMEWORKS[dep])
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name.startswith("vitest.config"):
            found.add("Vitest")
        elif name.startswith("jest.config"):
            found.add("Jest")
        elif name.startswith("playwright.config"):
            found.add("Playwright")
        elif name == "tsconfig.json":
            found.add("TypeScript compiler")
    return found


def analyse_structure(root: Path, scan: RepoScan) -> dict:
    files = {f.path for f in scan.files}
    lang_counter: Counter[str] = Counter()
    lang_bytes: Counter[str] = Counter()
    for f in scan.files:
        if f.language:
            lang_counter[f.language] += 1
            lang_bytes[f.language] += f.size

    py = inspect_python_config(root, files)
    js = inspect_package_json(root, files)
    frameworks = sorted(detect_python_frameworks(root, scan, py["dependencies"] + py["dev_dependencies"])
                        | detect_js_frameworks(js, files))

    top_dirs = Counter(f.path.split("/", 1)[0] for f in scan.files if "/" in f.path)
    test_dirs = sorted({f.path.rsplit("/", 1)[0] for f in scan.test_files() if "/" in f.path})
    source_dirs = sorted({f.path.rsplit("/", 1)[0] if "/" in f.path else "." for f in scan.source_files()})

    test_frameworks = []
    if "pytest" in frameworks or any(f.language == "Python" for f in scan.test_files()):
        test_frameworks.append("pytest")
    for fw in ("Vitest", "Jest", "Playwright", "Mocha"):
        if fw in frameworks:
            test_frameworks.append(fw)

    test_commands = list(js["test_commands"])
    if "pytest" in test_frameworks:
        test_commands.insert(0, "pytest")

    supported = [lang for lang in ("Python", "JavaScript", "TypeScript") if lang_counter.get(lang)]
    gaps = compute_testing_gaps(scan)

    return {
        "languages": [
            {"name": k, "files": v, "bytes": lang_bytes[k], "supported": k in ("Python", "JavaScript", "TypeScript")}
            for k, v in lang_counter.most_common()
        ],
        "supported_languages": supported,
        "frameworks": frameworks,
        "test_frameworks": test_frameworks,
        "test_commands": test_commands,
        "build_scripts": {k: v for k, v in js["scripts"].items() if k in ("build", "dev", "start", "lint", "typecheck")},
        "package_name": py.get("package_name") or js.get("package_name"),
        "dependencies": {
            "python": sorted(set(py["dependencies"])),
            "python_dev": sorted(set(py["dev_dependencies"])),
            "javascript": js["dependencies"],
            "javascript_dev": js["dev_dependencies"],
        },
        "config_files": sorted(f for f in files if f.rsplit("/", 1)[-1] in CONFIG_FILES),
        "top_level_directories": dict(top_dirs.most_common(20)),
        "source_directories": source_dirs[:50],
        "test_directories": test_dirs[:50],
        "totals": {
            "files": len(scan.files),
            "supported_source_files": len(scan.source_files()),
            "test_files": len(scan.test_files()),
            "skipped_files": len(scan.skipped),
        },
        "test_files": [f.path for f in scan.test_files()][:200],
        "testing_gaps": gaps,
        "skipped": scan.skipped[:100],
        "warnings": [w for w in (py.get("pyproject_error"), js.get("package_json_error")) if w],
    }


def compute_testing_gaps(scan: RepoScan) -> list[dict]:
    """Source modules with no test file that references their module name.

    This is a name-based heuristic and is labelled as such in the UI.
    """
    tests = scan.test_files()
    test_text = " ".join(t.path for t in tests)
    contents = []
    for t in tests:
        txt = read_text(scan.root, t.path)
        if txt:
            contents.append(txt)
    blob = test_text + "\n" + "\n".join(contents)
    gaps = []
    for f in scan.source_files():
        stem = Path(f.path).stem
        if stem in ("__init__", "index", "main", "setup", "conftest") or stem.endswith(".d"):
            continue
        if f.path.rsplit("/", 1)[-1].startswith(("vite.config", "vitest.config", "jest.config", "eslint.config")):
            continue
        if not re.search(rf"\b{re.escape(stem)}\b", blob):
            gaps.append({"file": f.path, "language": f.language, "reason": f"No test file references module '{stem}'"})
    return gaps[:100]
