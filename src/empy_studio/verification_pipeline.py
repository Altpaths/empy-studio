from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TextIO

from empy_studio.core.project_service import ProjectDetection
from empy_studio.dependency_bootstrap import composer_dependencies_required

VerificationCategory = Literal["tests", "build", "lint"]
VerificationStream = Literal["stdout", "stderr", "system"]
VerificationStatus = Literal["pending", "running", "pass", "fail"]
VerificationResultStatus = Literal["pass", "fail"]

DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 1800.0
DEFAULT_PROCESS_GRACE_SECONDS = 2.0
_AUTO_LINT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".empy",
        ".venv",
        "node_modules",
        "vendor",
        "build",
        "dist",
        "storage",
        "cache",
        "__pycache__",
    }
)
_COMMON_TOOL_PATHS = tuple(
    Path(item).expanduser()
    for item in (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
        "~/.local/bin",
        "~/.npm-global/bin",
    )
)


class VerificationCancelled(RuntimeError):
    """Raised after a verification subprocess has been stopped by the user."""


class VerificationTimedOut(RuntimeError):
    """Raised after a verification subprocess exceeds its bounded timeout."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    label: str
    category: VerificationCategory
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "label": self.label,
            "category": self.category,
            "command": list(self.command),
        }


@dataclass(frozen=True)
class VerificationEvent:
    timestamp: str
    check_id: str
    category: VerificationCategory
    stream: VerificationStream
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "check_id": self.check_id,
            "category": self.category,
            "stream": self.stream,
            "text": self.text,
        }


@dataclass(frozen=True)
class VerificationResult:
    check: VerificationCheck
    status: VerificationResultStatus
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.check.to_dict(),
            "status": self.status,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class VerificationReport:
    schema_version: int
    verification_id: str
    project_root: str
    project_type: str
    status: VerificationStatus
    started_at: str
    finished_at: str | None
    results: tuple[VerificationResult, ...]
    evidence_path: str
    finalized_at: str | None = None
    diagnostics: tuple[str, ...] = ()
    verification_root: str | None = None
    contract_signature: str | None = None

    @property
    def finalize_allowed(self) -> bool:
        return (
            self.status == "pass"
            and bool(self.results)
            and not self.diagnostics
            and all(item.status == "pass" for item in self.results)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "verification_id": self.verification_id,
            "project_root": self.project_root,
            "project_type": self.project_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": [item.to_dict() for item in self.results],
            "evidence_path": self.evidence_path,
            "finalize_allowed": self.finalize_allowed,
            "finalized_at": self.finalized_at,
            "diagnostics": list(self.diagnostics),
            "verification_root": self.verification_root,
            "contract_signature": self.contract_signature,
        }


@dataclass(frozen=True)
class VerificationPreflight:
    """Static readiness result shown before an Agent run starts."""

    checks: tuple[VerificationCheck, ...]
    diagnostics: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and not self.diagnostics

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "needs_attention",
            "checks": [item.label for item in self.checks],
            "diagnostics": list(self.diagnostics),
        }


def _node_scripts(root: Path) -> dict[str, object]:
    package = root / "package.json"
    if not package.is_file():
        return {}
    value = json.loads(package.read_text(encoding="utf-8"))
    scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
    return scripts if isinstance(scripts, dict) else {}


def _composer_scripts(root: Path) -> dict[str, object]:
    package = root / "composer.json"
    if not package.is_file():
        return {}
    value = json.loads(package.read_text(encoding="utf-8"))
    scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
    return scripts if isinstance(scripts, dict) else {}


def _php_source_files(root: Path) -> tuple[Path, ...]:
    """Return PHP source files that can be syntax-checked without executing them.

    A plain PHP project often has no Composer metadata or PHPUnit binary.  It
    still has a meaningful, safe verification gate: ``php -l`` parses each
    source file without running application code.  Dependency, generated, and
    Empy-owned directories are deliberately excluded.
    """

    source_files: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            directory
            for directory in directories
            if directory not in _AUTO_LINT_IGNORED_DIRECTORIES
            and not (current_path / directory).is_symlink()
        ]
        for filename in files:
            if not filename.lower().endswith(".php"):
                continue
            candidate = current_path / filename
            if candidate.is_symlink():
                continue
            source_files.append(candidate)
    return tuple(sorted(source_files, key=lambda path: path.relative_to(root).as_posix()))


def _verification_environment() -> dict[str, str]:
    """Return a subprocess environment that also works from a desktop launch."""

    environment = os.environ.copy()
    current_path = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
    for candidate in _COMMON_TOOL_PATHS:
        if candidate.is_dir() and str(candidate) not in current_path:
            current_path.append(str(candidate))
    if current_path:
        environment["PATH"] = os.pathsep.join(current_path)
    return environment


def _verification_category(value: object) -> VerificationCategory:
    if value == "tests":
        return "tests"
    if value == "build":
        return "build"
    if value == "lint":
        return "lint"
    raise ValueError("verification category must be tests, build, or lint")


def map_project_verification(detection: ProjectDetection) -> tuple[VerificationCheck, ...]:
    root = detection.effective_verification_root
    project_type = detection.descriptor.project_type
    checks: list[VerificationCheck] = []
    if project_type == "python":
        checks.extend(
            (
                VerificationCheck("tests", "Python tests", "tests", (sys.executable, "-m", "pytest", "-q")),
                VerificationCheck("build", "Python compilation", "build", (sys.executable, "-m", "compileall", "-q", "src")),
                VerificationCheck("lint", "Ruff lint", "lint", (sys.executable, "-m", "ruff", "check", ".")),
            )
        )
    elif project_type == "laravel":
        checks.append(VerificationCheck("tests", "Laravel tests", "tests", ("php", "artisan", "test")))
        checks.append(VerificationCheck("build", "Composer validation", "build", ("composer", "validate", "--no-check-publish")))
        pint = root / "vendor" / "bin" / "pint"
        if pint.is_file():
            checks.append(VerificationCheck("lint", "Laravel Pint", "lint", (str(pint), "--test")))
    elif project_type == "php":
        if (root / "composer.json").is_file():
            checks.append(
                VerificationCheck(
                    "build",
                    "Composer validation",
                    "build",
                    ("composer", "validate", "--no-check-publish"),
                )
            )
            composer_scripts = _composer_scripts(root)
            # Keep the declared test contract visible even when dependencies
            # are missing.  The preflight diagnostic below stops execution in
            # that case; silently omitting the check made a partial run look
            # like a successful verification.
            if "test" in composer_scripts:
                checks.append(
                    VerificationCheck(
                        "tests",
                        "Composer tests",
                        "tests",
                        ("composer", "--no-interaction", "run-script", "test"),
                    )
                )
        elif (root / "vendor" / "bin" / "phpunit").is_file():
            checks.append(
                VerificationCheck(
                    "tests",
                    "PHPUnit tests",
                    "tests",
                    (str(root / "vendor" / "bin" / "phpunit"),),
                )
            )
        else:
            for index, source_file in enumerate(_php_source_files(root), start=1):
                relative_path = source_file.relative_to(root).as_posix()
                checks.append(
                    VerificationCheck(
                        check_id=f"php-lint-{index}",
                        label=f"PHP syntax · {relative_path}",
                        category="lint",
                        command=("php", "-l", str(source_file)),
                    )
                )
    elif project_type == "node":
        scripts = _node_scripts(root)
        node_checks: tuple[tuple[VerificationCategory, str], ...] = (
            ("tests", "test"),
            ("build", "build"),
            ("lint", "lint"),
        )
        for node_category, script in node_checks:
            if script in scripts:
                checks.append(
                    VerificationCheck(
                        check_id=node_category,
                        label=f"npm {script}",
                        category=node_category,
                        command=("npm", "run", script),
                    )
                )
    elif project_type == "rust":
        checks.extend(
            (
                VerificationCheck("tests", "Cargo tests", "tests", ("cargo", "test")),
                VerificationCheck("build", "Cargo build", "build", ("cargo", "build")),
                VerificationCheck("lint", "Cargo clippy", "lint", ("cargo", "clippy", "--", "-D", "warnings")),
            )
        )
    elif project_type == "go":
        checks.extend(
            (
                VerificationCheck("tests", "Go tests", "tests", ("go", "test", "./...")),
                VerificationCheck("build", "Go build", "build", ("go", "build", "./...")),
                VerificationCheck("lint", "Go vet", "lint", ("go", "vet", "./...")),
            )
        )

    manifest = root / ".empy" / "verification.json"
    if manifest.is_file():
        value = json.loads(manifest.read_text(encoding="utf-8"))
        raw_checks = value.get("checks", []) if isinstance(value, dict) else []
        if not isinstance(raw_checks, list):
            raise TypeError("verification checks must be a list")
        checks = []
        for item in raw_checks:
            if not isinstance(item, dict):
                raise TypeError("verification check must be an object")
            command = item.get("command")
            if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
                raise TypeError("verification command must be a string list")
            manifest_category = _verification_category(item.get("category", "tests"))
            checks.append(
                VerificationCheck(
                    check_id=str(item["id"]),
                    label=str(item.get("label", item["id"])),
                    category=manifest_category,
                    command=tuple(command),
                )
            )
    return tuple(checks)


def _verification_diagnostics(detection: ProjectDetection) -> tuple[str, ...]:
    """Report required checks that could not be mapped safely."""

    root = detection.effective_verification_root
    diagnostics: list[str] = []
    if (
        detection.descriptor.project_type == "php"
        and (root / "composer.json").is_file()
        and composer_dependencies_required(root)
    ):
        scripts = _composer_scripts(root)
        if ("test" in scripts or "verify-release" in scripts) and not (
            root / "vendor" / "autoload.php"
        ).is_file():
            diagnostics.append(
                "Composer dependencies are not available in the isolated copy because "
                "vendor/autoload.php is missing. Empy will prepare them from composer.lock "
                "before the Agent and Verification; if Composer or the lockfile is unavailable, "
                "Empy will report that exact blocker instead of skipping the check."
            )
    return tuple(diagnostics)


def verification_preflight(detection: ProjectDetection) -> VerificationPreflight:
    """Inspect the verification contract without running project commands.

    Importing a project must surface missing runtime prerequisites before an
    Agent spends tokens on a ticket. This function is deliberately static: it
    does not install dependencies, execute project code, or modify the source
    copy.
    """

    diagnostics: list[str] = []
    try:
        checks = map_project_verification(detection)
    except (OSError, TypeError, ValueError) as exc:
        checks = ()
        diagnostics.append(f"Verification contract could not be read: {exc}")
    try:
        diagnostics.extend(_verification_diagnostics(detection))
    except (OSError, TypeError, ValueError) as exc:
        diagnostics.append(f"Verification prerequisites could not be read: {exc}")
    if not checks:
        diagnostics.append(
            "No safe verification checks were detected for this project. "
            "Configure .empy/verification.json or add a supported test, "
            "build, or lint entry point before export."
        )
    return VerificationPreflight(
        checks=tuple(checks),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def verification_contract_signature(
    detection: ProjectDetection,
    checks: tuple[VerificationCheck, ...] | None = None,
) -> str:
    """Return the contract identity used to produce verification evidence."""

    selected_checks = checks if checks is not None else map_project_verification(detection)
    payload = {
        "engine": "verification-contract-v2",
        "project_type": detection.descriptor.project_type,
        "verification_root": str(detection.effective_verification_root),
        "checks": [item.to_dict() for item in selected_checks],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verification_staleness_reason(
    report: VerificationReport,
    detection: ProjectDetection,
) -> str | None:
    """Explain why persisted evidence must not be trusted for this run."""

    expected = verification_contract_signature(detection)
    if report.contract_signature != expected:
        return (
            "Stored verification evidence was produced by an older or "
            "different verification contract. Re-run Verification before export."
        )
    return None


class VerificationRuntime:
    """Execute mapped verification checks and stream stdout/stderr evidence."""

    def run(
        self,
        *,
        detection: ProjectDetection,
        evidence_root: Path,
        on_event: Callable[[VerificationEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
        timeout_seconds: float = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    ) -> VerificationReport:
        if timeout_seconds < 1:
            raise ValueError("verification timeout must be at least one second")
        preflight = verification_preflight(detection)
        checks = preflight.checks
        contract_signature = verification_contract_signature(detection, checks)
        verification_id = uuid.uuid4().hex
        run_root = evidence_root / verification_id
        run_root.mkdir(parents=True, exist_ok=False)
        started_at = _now()
        results: list[VerificationResult] = []
        diagnostics = preflight.diagnostics
        if not checks:
            if on_event is not None:
                on_event(
                    VerificationEvent(
                        _now(),
                        "configuration",
                        "tests",
                        "system",
                        diagnostics[-1],
                    )
                )
        else:
            for check in checks:
                results.append(
                    self._run_check(
                        check,
                        detection.effective_verification_root,
                        run_root,
                        on_event,
                        cancel_event,
                        timeout_seconds,
                    )
                )
        status: VerificationStatus = (
            "pass"
            if checks and not diagnostics and all(item.status == "pass" for item in results)
            else "fail"
        )
        report = VerificationReport(
            schema_version=1,
            verification_id=verification_id,
            project_root=str(detection.descriptor.root),
            project_type=detection.descriptor.project_type,
            status=status,
            started_at=started_at,
            finished_at=_now(),
            results=tuple(results),
            evidence_path=str(run_root),
            diagnostics=diagnostics,
            verification_root=str(detection.effective_verification_root),
            contract_signature=contract_signature,
        )
        (run_root / "verification-report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report

    def _run_check(
        self,
        check: VerificationCheck,
        cwd: Path,
        run_root: Path,
        on_event: Callable[[VerificationEvent], None] | None,
        cancel_event: threading.Event | None,
        timeout_seconds: float,
    ) -> VerificationResult:
        if cancel_event is not None and cancel_event.is_set():
            raise VerificationCancelled("Verification was cancelled before it started.")
        started_at = _now()
        try:
            process = subprocess.Popen(
                check.command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_verification_environment(),
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            stderr = f"Unable to start verification command: {exc}\n"
            if on_event is not None:
                on_event(VerificationEvent(_now(), check.check_id, check.category, "system", stderr))
            (run_root / f"{check.check_id}.stdout.txt").write_text("", encoding="utf-8")
            (run_root / f"{check.check_id}.stderr.txt").write_text(stderr, encoding="utf-8")
            return VerificationResult(
                check=check,
                status="fail",
                returncode=127,
                stdout="",
                stderr=stderr,
                started_at=started_at,
                finished_at=_now(),
            )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def consume(
            stream: TextIO | None,
            name: Literal["stdout", "stderr"],
            sink: list[str],
        ) -> None:
            if stream is None:
                return
            while True:
                line = stream.readline()
                if line == "":
                    break
                sink.append(line)
                if on_event is not None:
                    on_event(VerificationEvent(_now(), check.check_id, check.category, name, line))

        stdout_thread = threading.Thread(target=consume, args=(process.stdout, "stdout", stdout_lines), daemon=True)
        stderr_thread = threading.Thread(target=consume, args=(process.stderr, "stderr", stderr_lines), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + timeout_seconds
        terminal_error: VerificationCancelled | VerificationTimedOut | None = None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                terminal_error = VerificationCancelled("Verification was cancelled.")
                self._terminate_process(process)
                break
            if time.monotonic() >= deadline:
                terminal_error = VerificationTimedOut(
                    f"Verification exceeded the {timeout_seconds:g}-second timeout."
                )
                self._terminate_process(process)
                break
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
        try:
            returncode = process.wait(timeout=DEFAULT_PROCESS_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill_process(process)
            returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        (run_root / f"{check.check_id}.stdout.txt").write_text(stdout, encoding="utf-8")
        (run_root / f"{check.check_id}.stderr.txt").write_text(stderr, encoding="utf-8")
        if terminal_error is not None:
            raise terminal_error
        return VerificationResult(
            check=check,
            status="pass" if returncode == 0 else "fail",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            finished_at=_now(),
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, AttributeError):
            process.terminate()

    @staticmethod
    def _kill_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, AttributeError):
            process.kill()


def finalize_verification(report: VerificationReport) -> VerificationReport:
    if not report.finalize_allowed:
        raise RuntimeError("Verification failures must be resolved before Finalize")
    return replace(report, finalized_at=_now())
