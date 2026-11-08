"""Execution-provider abstraction.

The API process never runs repository code. Test jobs are queued, picked up by
the separate worker process, and handed to an ``ExecutionProvider``:

* ``DisabledProvider``     – default; reports "execution unavailable"
* ``DockerSandboxProvider`` – one short-lived, locked-down container per job
* ``LocalTrustedProvider``  – development only, demo project only, Python only;
                              a subprocess with a scrubbed environment. NOT a sandbox.

Adding a provider (e.g. a remote sandbox service) means implementing
``availability`` and ``run``; nothing else in the application changes.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import REPO_ROOT, settings

log = logging.getLogger(__name__)


@dataclass
class ExecutionSpec:
    job_key: str
    language: str  # python | javascript
    work_dir: Path
    out_dir: Path
    include_existing: bool
    coverage: bool = True
    timeout: int = 120
    trusted_demo: bool = False


@dataclass
class ExecutionOutcome:
    status: str  # completed | timed_out | cancelled | infrastructure_error | unavailable
    duration_seconds: float = 0.0
    exit_code: int | None = None
    message: str | None = None
    details: dict = field(default_factory=dict)


class ExecutionProvider:
    name = "base"
    isolation = "none"

    def availability(self, spec: ExecutionSpec | None = None) -> tuple[bool, str]:
        raise NotImplementedError

    def run(self, spec: ExecutionSpec, should_cancel: Callable[[], bool]) -> ExecutionOutcome:
        raise NotImplementedError


class DisabledProvider(ExecutionProvider):
    name = "disabled"

    def availability(self, spec=None):
        return False, ("Test execution is disabled (EXECUTION_PROVIDER=disabled). Static analysis, test generation "
                       "and review remain available.")

    def run(self, spec, should_cancel):
        return ExecutionOutcome("unavailable", message=self.availability()[1])


def _docker_bin() -> str | None:
    return shutil.which("docker")


class DockerSandboxProvider(ExecutionProvider):
    name = "docker"
    isolation = "container"

    def availability(self, spec=None):
        exe = _docker_bin()
        if not exe:
            return False, "Docker CLI not found on the worker host"
        try:
            info = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True,
                                  timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False, "Docker daemon did not respond"
        if info.returncode != 0:
            return False, "Docker daemon is not running"
        img = subprocess.run([exe, "image", "inspect", settings.execution_image], capture_output=True, timeout=20)
        if img.returncode != 0:
            return False, (f"Runner image '{settings.execution_image}' not found. Build it with: "
                           "docker build -t testpilot-runner:latest execution-runner")
        return True, "Docker sandbox available"

    def build_command(self, spec: ExecutionSpec, container_name: str) -> list[str]:
        mem = f"{settings.execution_memory_mb}m"
        return [
            _docker_bin() or "docker", "run", "--rm", "--name", container_name,
            "--network", "none",                     # no network access
            "--read-only",                           # immutable root filesystem
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(settings.execution_pids_limit),
            "--memory", mem, "--memory-swap", mem,
            "--cpus", str(settings.execution_cpus),
            "--ulimit", "nofile=512:512",
            "--user", "65534:65534",                 # nobody
            "--env", "HOME=/tmp",
            "--label", "testpilot.job=" + spec.job_key,
            "-v", f"{spec.work_dir.resolve()}:/work:rw",
            "-v", f"{spec.out_dir.resolve()}:/out:rw",
            "--workdir", "/work",
            settings.execution_image,
            "--language", spec.language, "--work", "/work", "--out", "/out",
            "--include-existing", "1" if spec.include_existing else "0",
            "--coverage", "1" if spec.coverage else "0",
            "--timeout", str(spec.timeout),
        ]

    def run(self, spec, should_cancel):
        ok, reason = self.availability(spec)
        if not ok:
            return ExecutionOutcome("unavailable", message=reason)
        for d in (spec.work_dir, spec.out_dir):
            _make_world_writable(d)
        name = f"testpilot-{spec.job_key}"
        cmd = self.build_command(spec, name)
        start = time.monotonic()
        hard_deadline = start + spec.timeout + 30
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as exc:
            return ExecutionOutcome("infrastructure_error", message=f"Could not start container: {exc}")
        status = "completed"
        while proc.poll() is None:
            if should_cancel():
                status = "cancelled"
                break
            if time.monotonic() > hard_deadline:
                status = "timed_out"
                break
            time.sleep(1)
        if status != "completed":
            subprocess.run([_docker_bin() or "docker", "kill", name], capture_output=True, timeout=30)
            proc.wait(timeout=30)
        output = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", "replace")[-4000:]
        duration = time.monotonic() - start
        if status == "completed" and proc.returncode not in (0,):
            # Exit 125-127 = docker itself failed; 137 = killed (OOM)
            if proc.returncode == 137:
                return ExecutionOutcome("infrastructure_error", duration, proc.returncode,
                                        "Container was killed (likely exceeded the memory limit)")
            return ExecutionOutcome("infrastructure_error", duration, proc.returncode,
                                    f"Runner container exited with code {proc.returncode}: {output[-500:]}")
        return ExecutionOutcome(status, duration, proc.returncode, None, {"container": name})


def _make_world_writable(path: Path) -> None:
    if os.name == "nt":
        return
    for p in [path, *path.rglob("*")]:
        try:
            os.chmod(p, 0o777 if p.is_dir() else 0o666)
        except OSError:
            pass


class LocalTrustedProvider(ExecutionProvider):
    """Development convenience for the bundled demo project only. Provides NO isolation."""

    name = "local_trusted"
    isolation = "none (trusted demo code only)"

    def availability(self, spec=None):
        if settings.environment != "development" or not settings.allow_local_trusted_execution:
            return False, "local_trusted execution requires ENVIRONMENT=development and ALLOW_LOCAL_TRUSTED_EXECUTION=true"
        if spec is not None and not spec.trusted_demo:
            return False, "local_trusted execution only runs the bundled demo project; use the Docker sandbox for imported code"
        if spec is not None and spec.language != "python":
            return False, "local_trusted execution supports Python only; use the Docker sandbox for JavaScript/TypeScript"
        try:
            import pytest  # noqa: F401
            import coverage  # noqa: F401
        except ImportError:
            return False, "pytest and coverage must be installed for local_trusted execution"
        return True, "Local trusted runner (no isolation)"

    def run(self, spec, should_cancel):
        ok, reason = self.availability(spec)
        if not ok:
            return ExecutionOutcome("unavailable", message=reason)
        runner = REPO_ROOT / "execution-runner" / "runner.py"
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "TEMP": os.environ.get("TEMP", ""), "TMP": os.environ.get("TMP", ""), "HOME": str(spec.out_dir)}
        cmd = [sys.executable, "-I", str(runner), "--language", "python", "--work", str(spec.work_dir),
               "--out", str(spec.out_dir), "--include-existing", "1" if spec.include_existing else "0",
               "--coverage", "1" if spec.coverage else "0", "--timeout", str(spec.timeout)]
        start = time.monotonic()
        try:
            proc = subprocess.Popen(cmd, cwd=spec.work_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return ExecutionOutcome("infrastructure_error", message=str(exc))
        status = "completed"
        while proc.poll() is None:
            if should_cancel():
                status = "cancelled"
            elif time.monotonic() > start + spec.timeout + 30:
                status = "timed_out"
            if status != "completed":
                proc.kill()
                proc.wait()
                break
            time.sleep(0.5)
        return ExecutionOutcome(status, time.monotonic() - start, proc.returncode)


def get_execution_provider(name: str | None = None) -> ExecutionProvider:
    name = name or settings.execution_provider
    return {"docker": DockerSandboxProvider, "local_trusted": LocalTrustedProvider}.get(name, DisabledProvider)()
