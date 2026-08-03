from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class QualityRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class QualityCommand:
    name: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CoverageSummary:
    percent_covered: float
    covered_lines: int
    missing_lines: int
    total_statements: int
    threshold: float

    @property
    def passed(self) -> bool:
        return self.percent_covered >= self.threshold

    def validate(self) -> None:
        if not 0 <= self.percent_covered <= 100:
            raise ValueError(
                "Coverage percent must be between 0 and 100"
            )
        if not 0 <= self.threshold <= 100:
            raise ValueError(
                "Coverage threshold must be between 0 and 100"
            )
        if min(
            self.covered_lines,
            self.missing_lines,
            self.total_statements,
        ) < 0:
            raise ValueError(
                "Coverage counts cannot be negative"
            )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["passed"] = self.passed
        return value


@dataclass(frozen=True)
class QualityEvidence:
    schema_version: int
    status: str
    project_root: str
    project_digest: str
    commands: tuple[QualityCommand, ...]
    coverage: CoverageSummary

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def failed_commands(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            command.name
            for command in self.commands
            if not command.passed
        )

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported quality-evidence schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported quality-evidence status"
            )
        if len(self.project_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.project_digest.lower()
        ):
            raise ValueError(
                "project_digest must be SHA-256"
            )
        if not self.commands:
            raise ValueError(
                "Quality evidence must record commands"
            )

        self.coverage.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_root": self.project_root,
            "project_digest": self.project_digest,
            "failed_commands": list(
                self.failed_commands
            ),
            "commands": [
                command.to_dict()
                for command in self.commands
            ],
            "coverage": self.coverage.to_dict(),
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path


@dataclass(frozen=True)
class QualityConfig:
    project_root: str
    evidence_path: str
    coverage_json_path: str
    python_executable: str = sys.executable
    coverage_threshold: float = 80.0
    source_package: str = "src/empy_studio"
    test_path: str = "tests"

    def validate(self) -> None:
        root = Path(
            self.project_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise NotADirectoryError(root)
        if not (
            root / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "project_root must contain pyproject.toml"
            )
        if not self.python_executable.strip():
            raise ValueError(
                "python_executable cannot be empty"
            )
        if not 0 <= self.coverage_threshold <= 100:
            raise ValueError(
                "coverage_threshold must be between 0 and 100"
            )

        for relative in (
            self.source_package,
            self.test_path,
        ):
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "Quality paths must be safe relative paths"
                )


def _default_runner(
    command: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _project_digest(
    root: Path,
) -> str:
    digest = hashlib.sha256()
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "coverage.json",
        "htmlcov",
        "dist",
        "build",
    }

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(
            part in ignored
            for part in path.relative_to(root).parts
        ):
            continue

        relative = path.relative_to(
            root
        ).as_posix()
        digest.update(
            relative.encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(
            path.read_bytes()
        )

    return digest.hexdigest()


def load_coverage_summary(
    source: str | Path,
    *,
    threshold: float,
) -> CoverageSummary:
    path = Path(source).expanduser().resolve()
    value = json.loads(
        path.read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise TypeError(
            "Coverage JSON must contain an object"
        )

    totals = value.get("totals")
    if not isinstance(totals, dict):
        raise TypeError(
            "Coverage JSON totals must be an object"
        )

    summary = CoverageSummary(
        percent_covered=float(
            totals["percent_covered"]
        ),
        covered_lines=int(
            totals["covered_lines"]
        ),
        missing_lines=int(
            totals["missing_lines"]
        ),
        total_statements=int(
            totals["num_statements"]
        ),
        threshold=float(threshold),
    )
    summary.validate()
    return summary


def run_quality_gate(
    config: QualityConfig,
    *,
    runner: QualityRunner | None = None,
) -> QualityEvidence:
    config.validate()

    execute = runner or _default_runner
    root = Path(
        config.project_root
    ).expanduser().resolve()
    coverage_path = Path(
        config.coverage_json_path
    ).expanduser().resolve()
    coverage_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    commands: list[QualityCommand] = []

    command_specs = (
        (
            "ruff",
            [
                config.python_executable,
                "-m",
                "ruff",
                "check",
                ".",
            ],
        ),
        (
            "mypy",
            [
                config.python_executable,
                "-m",
                "mypy",
                "src",
            ],
        ),
        (
            "coverage",
            [
                config.python_executable,
                "-m",
                "coverage",
                "run",
                "--source",
                config.source_package,
                "-m",
                "pytest",
                config.test_path,
                "-q",
            ],
        ),
        (
            "coverage_json",
            [
                config.python_executable,
                "-m",
                "coverage",
                "json",
                "-o",
                str(coverage_path),
            ],
        ),
    )

    for name, command in command_specs:
        result = execute(
            command,
            cwd=root,
        )
        commands.append(
            QualityCommand(
                name=name,
                command=tuple(command),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )

        if result.returncode != 0:
            break

    if coverage_path.is_file():
        coverage = load_coverage_summary(
            coverage_path,
            threshold=(
                config.coverage_threshold
            ),
        )
    else:
        coverage = CoverageSummary(
            percent_covered=0.0,
            covered_lines=0,
            missing_lines=0,
            total_statements=0,
            threshold=(
                config.coverage_threshold
            ),
        )

    commands_passed = (
        len(commands) == len(command_specs)
        and all(
            command.passed
            for command in commands
        )
    )

    evidence = QualityEvidence(
        schema_version=1,
        status=(
            "passed"
            if commands_passed
            and coverage.passed
            else "failed"
        ),
        project_root=str(root),
        project_digest=_project_digest(
            root
        ),
        commands=tuple(commands),
        coverage=coverage,
    )
    evidence.save(
        config.evidence_path
    )
    return evidence


def require_quality_gate(
    evidence: QualityEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    blockers = list(
        evidence.failed_commands
    )
    if not evidence.coverage.passed:
        blockers.append(
            "coverage_threshold"
        )

    raise RuntimeError(
        "Quality gate failed: "
        + ", ".join(blockers)
    )
