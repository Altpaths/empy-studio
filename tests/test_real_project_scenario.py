from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from empy_studio.real_project_scenario import (
    RealProjectScenarioConfig,
    require_real_project_scenario,
    run_real_project_scenario,
)


def project_root(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "project-source"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[build-system]\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (
        root / "src" / "module.py"
    ).write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    return root


def scenario_root(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "scenario-source"
    root.mkdir()

    (root / "AGENTS.md").write_text(
        "# Agent instructions\n",
        encoding="utf-8",
    )
    (root / "task-contract.json").write_text(
        '{"task":"create evidence"}\n',
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        '{"tasks":[]}\n',
        encoding="utf-8",
    )
    return root


def completed(
    command: list[str],
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout="ok",
        stderr="",
    )


def test_real_project_scenario_passes(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)
    workspace = tmp_path / "workspace"

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        output_root = Path(
            env["EMPY_SCENARIO_OUTPUT"]
        )
        (
            output_root / "result.json"
        ).write_text(
            '{"status":"ok"}\n',
            encoding="utf-8",
        )
        (
            output_root / "evidence.json"
        ).write_text(
            '{"evidence":true}\n',
            encoding="utf-8",
        )
        return completed(command)

    evidence_path = (
        tmp_path / "scenario-evidence.json"
    )

    evidence = run_real_project_scenario(
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                evidence_path
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "manifest.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
                "evidence.json",
            ),
        ),
        runner=runner,
        workspace_root=workspace,
    )

    assert evidence.status == "passed"
    assert evidence_path.is_file()
    assert evidence.verified_outputs == (
        "evidence.json",
        "result.json",
    )


def test_runtime_failure_blocks_scenario(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            returncode=1,
        )

    evidence = run_real_project_scenario(
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "manifest.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    assert evidence.status == "failed"
    assert (
        evidence.commands[0].name
        == "runtime_run"
    )


def test_missing_output_blocks_scenario(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_real_project_scenario(
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "manifest.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    assert evidence.status == "failed"
    assert evidence.verified_outputs == ()


def test_scenario_copy_excludes_git(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)
    (scenario / ".git").mkdir()
    workspace = tmp_path / "workspace"

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        output_root = Path(
            env["EMPY_SCENARIO_OUTPUT"]
        )
        (
            output_root / "result.json"
        ).write_text(
            "{}",
            encoding="utf-8",
        )
        return completed(command)

    run_real_project_scenario(
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "manifest.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
            ),
        ),
        runner=runner,
        workspace_root=workspace,
    )

    assert not (
        workspace
        / "scenario"
        / ".git"
    ).exists()


def test_require_scenario_raises(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            returncode=1,
        )

    evidence = run_real_project_scenario(
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "manifest.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="runtime_run",
    ):
        require_real_project_scenario(
            evidence
        )


def test_rejects_missing_manifest(
    tmp_path: Path,
) -> None:
    project = project_root(tmp_path)
    scenario = scenario_root(tmp_path)

    with pytest.raises(
        FileNotFoundError,
    ):
        RealProjectScenarioConfig(
            source_root=str(project),
            scenario_root=str(scenario),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
            cli_executable="empy",
            manifest_path=str(
                scenario / "missing.json"
            ),
            output_root="outputs",
            expected_outputs=(
                "result.json",
            ),
        ).validate()
