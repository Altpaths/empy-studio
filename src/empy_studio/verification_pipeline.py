from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TextIO

from empy_studio.core.project_service import ProjectDetection

VerificationCategory = Literal["tests", "build", "lint"]
VerificationStream = Literal["stdout", "stderr", "system"]
VerificationStatus = Literal["pending", "running", "pass", "fail"]
VerificationResultStatus = Literal["pass", "fail"]


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

    @property
    def finalize_allowed(self) -> bool:
        return self.status == "pass" and bool(self.results) and all(
            item.status == "pass" for item in self.results
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


def _verification_category(value: object) -> VerificationCategory:
    if value == "tests":
        return "tests"
    if value == "build":
        return "build"
    if value == "lint":
        return "lint"
    raise ValueError("verification category must be tests, build, or lint")


def map_project_verification(detection: ProjectDetection) -> tuple[VerificationCheck, ...]:
    root = detection.descriptor.root
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
            if (root / "vendor" / "autoload.php").is_file() and "test" in composer_scripts:
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


class VerificationRuntime:
    """Execute mapped verification checks and stream stdout/stderr evidence."""

    def run(
        self,
        *,
        detection: ProjectDetection,
        evidence_root: Path,
        on_event: Callable[[VerificationEvent], None] | None = None,
    ) -> VerificationReport:
        checks = map_project_verification(detection)
        if not checks:
            raise RuntimeError("No verification commands are mapped for this project")
        verification_id = uuid.uuid4().hex
        run_root = evidence_root / verification_id
        run_root.mkdir(parents=True, exist_ok=False)
        started_at = _now()
        results: list[VerificationResult] = []
        for check in checks:
            results.append(self._run_check(check, detection.descriptor.root, run_root, on_event))
        status: VerificationStatus = "pass" if all(item.status == "pass" for item in results) else "fail"
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
    ) -> VerificationResult:
        started_at = _now()
        process = subprocess.Popen(
            check.command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
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
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        (run_root / f"{check.check_id}.stdout.txt").write_text(stdout, encoding="utf-8")
        (run_root / f"{check.check_id}.stderr.txt").write_text(stderr, encoding="utf-8")
        return VerificationResult(
            check=check,
            status="pass" if returncode == 0 else "fail",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            finished_at=_now(),
        )


def finalize_verification(report: VerificationReport) -> VerificationReport:
    if not report.finalize_allowed:
        raise RuntimeError("Verification failures must be resolved before Finalize")
    return replace(report, finalized_at=_now())
