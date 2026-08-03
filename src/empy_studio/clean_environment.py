from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class CleanEnvironmentCommand:
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
class CleanEnvironmentEvidence:
    schema_version: int
    status: str
    source_root: str
    workspace_root: str
    venv_root: str
    python_executable: str
    project_digest: str
    commands: tuple[CleanEnvironmentCommand, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported clean-environment schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported clean-environment status"
            )
        if len(self.project_digest) != 64:
            raise ValueError(
                "project_digest must be SHA-256"
            )
        if not self.commands:
            raise ValueError(
                "Clean environment must record commands"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_root": self.source_root,
            "workspace_root": self.workspace_root,
            "venv_root": self.venv_root,
            "python_executable": self.python_executable,
            "project_digest": self.project_digest,
            "commands": [
                command.to_dict()
                for command in self.commands
            ],
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
class CleanEnvironmentConfig:
    source_root: str
    evidence_path: str
    python_executable: str = sys.executable
    install_target: str = "."
    cli_command: tuple[str, ...] = (
        "empy",
        "--help",
    )
    preserve_workspace: bool = False

    def validate(self) -> None:
        source = Path(
            self.source_root
        ).expanduser().resolve()

        if not source.is_dir():
            raise NotADirectoryError(source)
        if not (
            source / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "source_root must contain pyproject.toml"
            )
        if not self.python_executable.strip():
            raise ValueError(
                "python_executable cannot be empty"
            )
        if not self.cli_command:
            raise ValueError(
                "cli_command cannot be empty"
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

    ignored_parts = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(
            part in ignored_parts
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

        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)

    return digest.hexdigest()


def _copy_project(
    source: Path,
    destination: Path,
) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.pyc",
    )
    shutil.copytree(
        source,
        destination,
        ignore=ignored,
    )


def _venv_python(
    venv_root: Path,
) -> Path:
    if os.name == "nt":
        return (
            venv_root
            / "Scripts"
            / "python.exe"
        )

    return (
        venv_root
        / "bin"
        / "python"
    )


def _venv_command(
    venv_root: Path,
    command_name: str,
) -> Path:
    if os.name == "nt":
        suffix = (
            ".exe"
            if command_name == "empy"
            else ""
        )
        return (
            venv_root
            / "Scripts"
            / f"{command_name}{suffix}"
        )

    return (
        venv_root
        / "bin"
        / command_name
    )


def run_clean_environment(
    config: CleanEnvironmentConfig,
    *,
    runner: CommandRunner | None = None,
    workspace_root: str | Path | None = None,
) -> CleanEnvironmentEvidence:
    config.validate()

    execute = runner or _default_runner
    source = Path(
        config.source_root
    ).expanduser().resolve()

    managed_workspace = (
        workspace_root is None
    )
    if managed_workspace:
        workspace = Path(
            tempfile.mkdtemp(
                prefix="empy-rc-clean-",
            )
        )
    else:
        assert workspace_root is not None
        workspace = Path(
            workspace_root
        ).expanduser().resolve()

    project_root = (
        workspace / "project"
    )
    venv_root = (
        workspace / "venv"
    )
    records: list[
        CleanEnvironmentCommand
    ] = []

    def run_step(
        name: str,
        command: list[str],
        cwd: Path,
    ) -> bool:
        result = execute(
            command,
            cwd=cwd,
        )
        record = CleanEnvironmentCommand(
            name=name,
            command=tuple(command),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        records.append(record)
        return record.passed

    try:
        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )
        _copy_project(
            source,
            project_root,
        )

        if not run_step(
            "create_venv",
            [
                config.python_executable,
                "-m",
                "venv",
                str(venv_root),
            ],
            project_root,
        ):
            status = "failed"
        else:
            python_path = _venv_python(
                venv_root
            )

            install_ok = run_step(
                "install_project",
                [
                    str(python_path),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    config.install_target,
                ],
                project_root,
            )

            cli_ok = False
            if install_ok:
                command = list(
                    config.cli_command
                )
                command[0] = str(
                    _venv_command(
                        venv_root,
                        command[0],
                    )
                )
                cli_ok = run_step(
                    "verify_cli",
                    command,
                    project_root,
                )

            status = (
                "passed"
                if install_ok and cli_ok
                else "failed"
            )

        evidence = CleanEnvironmentEvidence(
            schema_version=1,
            status=status,
            source_root=str(source),
            workspace_root=str(workspace),
            venv_root=str(venv_root),
            python_executable=(
                str(
                    _venv_python(
                        venv_root
                    )
                )
            ),
            project_digest=(
                _project_digest(source)
            ),
            commands=tuple(records),
        )
        evidence.save(
            config.evidence_path
        )
        return evidence

    finally:
        if (
            managed_workspace
            and not config.preserve_workspace
        ):
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )


def require_clean_environment(
    evidence: CleanEnvironmentEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    failed = [
        command.name
        for command in evidence.commands
        if not command.passed
    ]
    raise RuntimeError(
        "Clean environment validation failed: "
        + ", ".join(failed)
    )
