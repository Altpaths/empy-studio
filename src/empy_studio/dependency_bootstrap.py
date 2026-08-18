from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from empy_studio.core.project_service import ProjectDetection

DependencyBootstrapStatus = Literal[
    "not_needed",
    "prepared",
    "unavailable",
    "failed",
]
DependencyManager = Literal["composer", "npm"]

DEFAULT_BOOTSTRAP_TIMEOUT_SECONDS = 900.0
_TOOL_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "~/.local/bin",
    "~/.npm-global/bin",
)


@dataclass(frozen=True)
class DependencyBootstrapPlan:
    manager: DependencyManager
    root: Path
    command: tuple[str, ...]
    lockfile: Path | None
    generated_scope: str
    reason: str
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class DependencyBootstrapResult:
    status: DependencyBootstrapStatus
    manager: DependencyManager | None
    root: str
    command: tuple[str, ...]
    returncode: int | None
    message: str
    stdout: str = ""
    stderr: str = ""
    generated_scope: str | None = None

    @property
    def successful(self) -> bool:
        return self.status in {"not_needed", "prepared"}

    @property
    def retryable(self) -> bool:
        return self.status in {"unavailable", "failed"}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "manager": self.manager,
            "root": self.root,
            "command": list(self.command),
            "returncode": self.returncode,
            "message": self.message,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "generated_scope": self.generated_scope,
            "successful": self.successful,
            "retryable": self.retryable,
        }


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    path = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
    for raw in _TOOL_PATHS:
        candidate = Path(raw).expanduser()
        if candidate.is_dir() and str(candidate) not in path:
            path.append(str(candidate))
    if path:
        environment["PATH"] = os.pathsep.join(path)
    return environment


def _which(command: str, environment: dict[str, str]) -> str | None:
    """Find a tool without sharing the mutable ``shutil.which`` test hook."""

    candidates = [command]
    if os.name == "nt":
        suffixes = tuple(
            item for item in environment.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if item
        )
        candidates.extend(command + suffix for suffix in suffixes)
    for directory in environment.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for candidate_name in candidates:
            candidate = Path(directory) / candidate_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _scripts(root: Path, filename: str) -> dict[str, object]:
    manifest = root / filename
    if not manifest.is_file():
        return {}
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    raw = value.get("scripts", {}) if isinstance(value, dict) else {}
    return raw if isinstance(raw, dict) else {}


def composer_dependencies_required(root: Path) -> bool:
    """Return whether Composer's generated autoloader is part of the contract."""

    manifest = root / "composer.json"
    if not manifest.is_file():
        return False
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return True
    if not isinstance(value, dict):
        return True
    for section_name in ("require", "require-dev"):
        section = value.get(section_name, {})
        if not isinstance(section, dict):
            continue
        if any(
            (
                str(name).casefold() != "php"
                and not str(name).casefold().startswith(("ext-", "lib-"))
            )
            for name in section
        ):
            return True
    if isinstance(value.get("autoload"), dict) or isinstance(value.get("autoload-dev"), dict):
        return True
    scripts = value.get("scripts", {})
    if isinstance(scripts, dict):
        return any(
            "vendor/" in str(command).casefold()
            for command in scripts.values()
        )
    return False


def _unavailable_plan(
    manager: DependencyManager,
    root: Path,
    *,
    lockfile: Path | None,
    generated_scope: str,
    reason: str,
    unavailable_reason: str,
) -> DependencyBootstrapPlan:
    return DependencyBootstrapPlan(
        manager=manager,
        root=root,
        command=(),
        lockfile=lockfile,
        generated_scope=generated_scope,
        reason=reason,
        unavailable_reason=unavailable_reason,
    )


def dependency_bootstrap_plan(
    detection: ProjectDetection,
) -> DependencyBootstrapPlan | None:
    """Return a bounded dependency-preparation plan for the isolated project.

    Only lockfile-backed, well-known package-manager commands are automated.
    Empy never executes a project's lifecycle scripts merely to make a check
    pass, and it never installs dependencies into the user's original folder.
    """

    root = detection.effective_verification_root
    environment = _environment()

    composer_json = root / "composer.json"
    composer_lock = root / "composer.lock"
    composer_scripts = _scripts(root, "composer.json")
    composer_needed = (
        detection.descriptor.project_type == "laravel"
        or (
            ("test" in composer_scripts or "verify-release" in composer_scripts)
            and composer_dependencies_required(root)
        )
    )
    if (
        composer_json.is_file()
        and composer_needed
        and not (root / "vendor" / "autoload.php").is_file()
    ):
        composer = _which("composer", environment)
        reason = "Composer verification dependencies are missing from the isolated copy."
        if composer is None:
            return _unavailable_plan(
                "composer",
                root,
                lockfile=composer_lock if composer_lock.is_file() else None,
                generated_scope="vendor/",
                reason=reason,
                unavailable_reason=(
                    "Composer is not installed or is not visible to Empy. "
                    "Install Composer once, then retry; Empy will not change the original project."
                ),
            )
        if not composer_lock.is_file():
            return _unavailable_plan(
                "composer",
                root,
                lockfile=None,
                generated_scope="vendor/",
                reason=reason,
                unavailable_reason=(
                    "composer.lock is missing. Empy will not resolve unpinned dependencies "
                    "silently; add and review composer.lock, then retry."
                ),
            )
        return DependencyBootstrapPlan(
            manager="composer",
            root=root,
            command=(
                composer,
                "install",
                "--no-interaction",
                "--no-progress",
                "--prefer-dist",
                "--no-scripts",
                "--no-plugins",
            ),
            lockfile=composer_lock,
            generated_scope="vendor/",
            reason=reason,
        )

    package_json = root / "package.json"
    package_scripts = _scripts(root, "package.json")
    node_needed = any(name in package_scripts for name in ("test", "build", "lint"))
    node_modules = root / "node_modules"
    if package_json.is_file() and node_needed and not node_modules.is_dir():
        package_lock = root / "package-lock.json"
        npm = _which("npm", environment)
        reason = "Node verification dependencies are missing from the isolated copy."
        if npm is None:
            return _unavailable_plan(
                "npm",
                root,
                lockfile=package_lock if package_lock.is_file() else None,
                generated_scope="node_modules/",
                reason=reason,
                unavailable_reason=(
                    "npm is not installed or is not visible to Empy. "
                    "Install Node.js once, then retry."
                ),
            )
        if not package_lock.is_file():
            return _unavailable_plan(
                "npm",
                root,
                lockfile=None,
                generated_scope="node_modules/",
                reason=reason,
                unavailable_reason=(
                    "package-lock.json is missing. Empy will not resolve unpinned Node "
                    "dependencies silently; add and review the lockfile, then retry."
                ),
            )
        return DependencyBootstrapPlan(
            manager="npm",
            root=root,
            command=(
                npm,
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ),
            lockfile=package_lock,
            generated_scope="node_modules/",
            reason=reason,
        )

    return None


def _trim_output(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return "...[truncated]...\n" + value[-limit:]


def _terminate(process: subprocess.Popen[str], *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (OSError, AttributeError):
        process.kill() if force else process.terminate()


def _run_command(
    plan: DependencyBootstrapPlan,
    *,
    cancel_event: threading.Event | None,
    timeout_seconds: float,
    on_output: Callable[[str, str], None] | None,
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        plan.command,
        cwd=plan.root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(),
        start_new_session=(os.name == "posix"),
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def consume(
        stream: TextIO | None,
        name: str,
        sink: list[str],
    ) -> None:
        if stream is None:
            return
        while True:
            line = stream.readline()
            if line == "":
                return
            sink.append(line)
            if on_output is not None:
                on_output(name, line.rstrip())

    stdout_thread = threading.Thread(
        target=consume,
        args=(process.stdout, "stdout", stdout_lines),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=consume,
        args=(process.stderr, "stderr", stderr_lines),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + timeout_seconds
    stopped = False
    while process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            stopped = True
            _terminate(process)
            break
        if time.monotonic() >= deadline:
            stopped = True
            _terminate(process)
            break
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            continue
    try:
        returncode = process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        _terminate(process, force=True)
        returncode = process.wait()
    stdout_thread.join(timeout=2.0)
    stderr_thread.join(timeout=2.0)
    if stopped and returncode == 0:
        returncode = 124
    return returncode, _trim_output("".join(stdout_lines)), _trim_output("".join(stderr_lines))


def prepare_project_dependencies(
    detection: ProjectDetection,
    *,
    cancel_event: threading.Event | None = None,
    timeout_seconds: float = DEFAULT_BOOTSTRAP_TIMEOUT_SECONDS,
    on_output: Callable[[str, str], None] | None = None,
) -> DependencyBootstrapResult:
    """Prepare real dependencies in Empy's isolated verification copy.

    The function is intentionally idempotent. Existing dependencies are
    reused, generated dependency directories stay outside the delivery ZIP,
    and missing lockfiles/tools are reported as actionable blockers rather than
    being replaced with fake files or a skipped test.
    """

    if timeout_seconds < 1:
        raise ValueError("dependency bootstrap timeout must be at least one second")
    plan = dependency_bootstrap_plan(detection)
    root = detection.effective_verification_root
    if plan is None:
        return DependencyBootstrapResult(
            status="not_needed",
            manager=None,
            root=str(root),
            command=(),
            returncode=0,
            message="No isolated dependency bootstrap was required.",
        )
    if plan.unavailable_reason is not None:
        return DependencyBootstrapResult(
            status="unavailable",
            manager=plan.manager,
            root=str(plan.root),
            command=plan.command,
            returncode=None,
            message=plan.unavailable_reason,
            generated_scope=plan.generated_scope,
        )
    try:
        returncode, stdout, stderr = _run_command(
            plan,
            cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,
            on_output=on_output,
        )
    except OSError as exc:
        return DependencyBootstrapResult(
            status="failed",
            manager=plan.manager,
            root=str(plan.root),
            command=plan.command,
            returncode=127,
            message=f"Empy could not start {plan.manager} dependency preparation: {exc}",
            stderr=str(exc),
            generated_scope=plan.generated_scope,
        )
    if returncode != 0:
        detail = stderr.strip() or stdout.strip()
        suffix = f" Details: {detail[-1600:]}" if detail else ""
        return DependencyBootstrapResult(
            status="failed",
            manager=plan.manager,
            root=str(plan.root),
            command=plan.command,
            returncode=returncode,
            message=(
                f"Empy tried to prepare {plan.manager} dependencies in the isolated copy, "
                f"but the command failed with exit code {returncode}.{suffix}"
            ),
            stdout=stdout,
            stderr=stderr,
            generated_scope=plan.generated_scope,
        )
    artifact = (
        plan.root / "vendor" / "autoload.php"
        if plan.manager == "composer"
        else plan.root / "node_modules"
    )
    if not artifact.exists():
        return DependencyBootstrapResult(
            status="failed",
            manager=plan.manager,
            root=str(plan.root),
            command=plan.command,
            returncode=0,
            message=(
                f"{plan.manager} finished without creating the required {plan.generated_scope} "
                "artifact; Verification was not allowed to continue."
            ),
            stdout=stdout,
            stderr=stderr,
            generated_scope=plan.generated_scope,
        )
    return DependencyBootstrapResult(
        status="prepared",
        manager=plan.manager,
        root=str(plan.root),
        command=plan.command,
        returncode=0,
        message=(
            f"Empy prepared {plan.manager} dependencies in the isolated copy. "
            f"{plan.generated_scope} is excluded from the final change-only ZIP."
        ),
        stdout=stdout,
        stderr=stderr,
        generated_scope=plan.generated_scope,
    )
