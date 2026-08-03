from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class ScenarioRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class ScenarioCommand:
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
class RealProjectScenarioConfig:
    source_root: str
    scenario_root: str
    evidence_path: str
    cli_executable: str
    manifest_path: str
    output_root: str
    expected_outputs: tuple[str, ...]
    preserve_workspace: bool = False

    def validate(self) -> None:
        source = Path(
            self.source_root
        ).expanduser().resolve()
        scenario = Path(
            self.scenario_root
        ).expanduser().resolve()
        manifest = Path(
            self.manifest_path
        ).expanduser().resolve()

        if not source.is_dir():
            raise NotADirectoryError(source)
        if not (
            source / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "source_root must contain pyproject.toml"
            )
        if not scenario.is_dir():
            raise NotADirectoryError(scenario)
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        if not self.cli_executable.strip():
            raise ValueError(
                "cli_executable cannot be empty"
            )
        if not self.expected_outputs:
            raise ValueError(
                "expected_outputs cannot be empty"
            )


@dataclass(frozen=True)
class RealProjectScenarioEvidence:
    schema_version: int
    status: str
    source_root: str
    scenario_root: str
    workspace_root: str
    project_digest: str
    scenario_digest: str
    commands: tuple[ScenarioCommand, ...]
    verified_outputs: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported scenario evidence schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported scenario evidence status"
            )
        for digest in (
            self.project_digest,
            self.scenario_digest,
        ):
            if len(digest) != 64:
                raise ValueError(
                    "Scenario digests must be SHA-256"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_root": self.source_root,
            "scenario_root": self.scenario_root,
            "workspace_root": self.workspace_root,
            "project_digest": self.project_digest,
            "scenario_digest": self.scenario_digest,
            "commands": [
                command.to_dict()
                for command in self.commands
            ],
            "verified_outputs": list(
                self.verified_outputs
            ),
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


def _default_runner(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _tree_digest(
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


def _copy_tree(
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


def run_real_project_scenario(
    config: RealProjectScenarioConfig,
    *,
    runner: ScenarioRunner | None = None,
    workspace_root: str | Path | None = None,
) -> RealProjectScenarioEvidence:
    config.validate()

    execute = runner or _default_runner
    source = Path(
        config.source_root
    ).expanduser().resolve()
    scenario = Path(
        config.scenario_root
    ).expanduser().resolve()
    manifest = Path(
        config.manifest_path
    ).expanduser().resolve()

    managed_workspace = (
        workspace_root is None
    )
    if managed_workspace:
        workspace = Path(
            tempfile.mkdtemp(
                prefix="empy-rc-scenario-",
            )
        )
    else:
        assert workspace_root is not None
        workspace = Path(
            workspace_root
        ).expanduser().resolve()

    project_copy = workspace / "project"
    scenario_copy = workspace / "scenario"
    output_root = (
        workspace / config.output_root
    )

    commands: list[ScenarioCommand] = []
    verified_outputs: list[str] = []

    def run_step(
        name: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
    ) -> bool:
        result = execute(
            command,
            cwd=cwd,
            env=env,
        )
        record = ScenarioCommand(
            name=name,
            command=tuple(command),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        commands.append(record)
        return record.passed

    try:
        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )
        _copy_tree(
            source,
            project_copy,
        )
        _copy_tree(
            scenario,
            scenario_copy,
        )
        output_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        copied_manifest = (
            scenario_copy
            / manifest.relative_to(scenario)
        )

        environment = os.environ.copy()
        environment["EMPY_SCENARIO_MODE"] = "1"
        environment["EMPY_SCENARIO_OUTPUT"] = str(
            output_root
        )

        command = [
            config.cli_executable,
            "runtime",
            "run",
            "--manifest",
            str(copied_manifest),
            "--output-root",
            str(output_root),
        ]

        runtime_ok = run_step(
            "runtime_run",
            command,
            project_copy,
            environment,
        )

        outputs_ok = True
        if runtime_ok:
            for relative in (
                config.expected_outputs
            ):
                path = (
                    output_root / relative
                ).resolve()

                if (
                    output_root
                    not in path.parents
                    and path != output_root
                ):
                    raise ValueError(
                        "Expected output escapes "
                        "scenario output root"
                    )

                if not path.is_file():
                    outputs_ok = False
                    continue

                verified_outputs.append(
                    path.relative_to(
                        output_root
                    ).as_posix()
                )

        status = (
            "passed"
            if runtime_ok and outputs_ok
            else "failed"
        )

        evidence = RealProjectScenarioEvidence(
            schema_version=1,
            status=status,
            source_root=str(source),
            scenario_root=str(scenario),
            workspace_root=str(workspace),
            project_digest=_tree_digest(
                source
            ),
            scenario_digest=_tree_digest(
                scenario
            ),
            commands=tuple(commands),
            verified_outputs=tuple(
                sorted(verified_outputs)
            ),
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


def require_real_project_scenario(
    evidence: RealProjectScenarioEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    failed_commands = [
        item.name
        for item in evidence.commands
        if not item.passed
    ]
    detail = (
        ", ".join(failed_commands)
        if failed_commands
        else "expected outputs missing"
    )
    raise RuntimeError(
        "Real project scenario failed: "
        + detail
    )
