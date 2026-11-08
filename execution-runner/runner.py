"""TestPilot in-sandbox test runner.

Runs INSIDE the isolated execution environment (the Docker image built from
this directory). It never talks to the TestPilot API or database: it reads the
prepared workspace from --work, runs the test tool and writes machine-readable
results to --out:

    out/junit.xml        test results (pytest or Vitest JUnit reporter)
    out/coverage.json    coverage.py JSON report (Python)
    out/coverage/coverage-summary.json   Vitest v8 json-summary (JS/TS)
    out/runner.json      exit codes and timings of each step
    out/output.log       combined stdout/stderr (truncated)

Only the Python standard library is used here.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MAX_LOG = 400_000


def run(cmd: list[str], cwd: Path, timeout: int, log, env: dict) -> dict:
    start = time.monotonic()
    log.write(f"$ {' '.join(cmd)}\n")
    log.flush()
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        out = proc.stdout.decode("utf-8", "replace")
        log.write(out[-MAX_LOG:])
        return {"cmd": cmd[:3], "exit_code": proc.returncode, "seconds": round(time.monotonic() - start, 3)}
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else ""
        log.write(out[-MAX_LOG:] + f"\n[runner] step timed out after {timeout}s\n")
        return {"cmd": cmd[:3], "exit_code": None, "timed_out": True, "seconds": round(time.monotonic() - start, 3)}


def python_steps(work: Path, out: Path, include_existing: bool, coverage: bool) -> list[list[str]]:
    targets = ["."] if include_existing else ["testpilot_generated"]
    pytest_args = ["-m", "pytest", "-p", "no:cacheprovider", "-q", "-o", "addopts=", "--rootdir", str(work),
                   f"--junitxml={out / 'junit.xml'}", "-o", "junit_family=xunit2", *targets]
    if not coverage:
        return [[sys.executable, *pytest_args]]
    data = str(out / ".coverage")
    omit = "*/testpilot_generated/*,*/tests/*,*/test_*.py,*_test.py,*/conftest.py"
    return [
        [sys.executable, "-m", "coverage", "run", f"--data-file={data}", "--branch", f"--source={work}",
         f"--omit={omit}", *pytest_args],
        [sys.executable, "-m", "coverage", "json", f"--data-file={data}", "-o", str(out / "coverage.json"),
         "--ignore-errors"],
    ]


def js_steps(work: Path, out: Path, include_existing: bool, coverage: bool, vitest_dir: Path) -> list[list[str]]:
    vitest = str(vitest_dir / "node_modules" / "vitest" / "vitest.mjs")
    config = str(vitest_dir / "vitest.config.mjs")
    cmd = ["node", vitest, "run", "--root", str(work), "--config", config, "--configLoader", "runner",
           "--reporter=junit", f"--outputFile={out / 'junit.xml'}"]
    if not include_existing:
        cmd.append("testpilot_generated")
    if coverage:  # v8 provider is configured in vitest.config.mjs
        cmd += ["--coverage.enabled=true", "--coverage.reporter=json-summary",
                f"--coverage.reportsDirectory={out / 'coverage'}"]
    return [cmd]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", choices=["python", "javascript"], required=True)
    ap.add_argument("--work", default="/work")
    ap.add_argument("--out", default="/out")
    ap.add_argument("--include-existing", default="1")
    ap.add_argument("--coverage", default="1")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--vitest-dir", default="/opt/runner")
    args = ap.parse_args()

    work, out = Path(args.work), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    include_existing = args.include_existing == "1"
    coverage = args.coverage == "1"
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([str(work), str(work / "src")]),
        "CI": "1",
        "NO_COLOR": "1",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    for k in ("SYSTEMROOT", "TEMP", "TMP"):  # needed on Windows (local trusted runner only)
        if k in os.environ:
            env[k] = os.environ[k]

    steps = (python_steps(work, out, include_existing, coverage) if args.language == "python"
             else js_steps(work, out, include_existing, coverage, Path(args.vitest_dir)))
    deadline = time.monotonic() + args.timeout
    report = {"language": args.language, "steps": []}
    with open(out / "output.log", "w", encoding="utf-8", errors="replace") as log:
        for cmd in steps:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                report["timed_out"] = True
                break
            res = run(cmd, work, remaining, log, env)
            report["steps"].append(res)
            if res.get("timed_out"):
                report["timed_out"] = True
                break
    report["test_exit_code"] = report["steps"][0]["exit_code"] if report["steps"] else None
    (out / "runner.json").write_text(json.dumps(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
