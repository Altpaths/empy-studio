from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from empy_studio.clean_environment import (
    CleanEnvironmentConfig,
    require_clean_environment,
    run_clean_environment,
)


def source_project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "source"
    root.mkdir()

    (root / "pyproject.toml").write_text(
        "[build-system]\n",
        encoding="utf-8",
    )
    package = root / "src"
    package.mkdir()
    (package / "module.py").write_text(
        "VALUE = 1\n",
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


def test_clean_environment_passes(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )
    calls: list[
        tuple[str, ...]
    ] = []

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return completed(command)

    evidence_path = (
        tmp_path / "evidence.json"
    )

    evidence = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                evidence_path
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    assert evidence.status == "passed"
    assert evidence_path.is_file()
    assert [
        item.name
        for item in evidence.commands
    ] == [
        "create_venv",
        "install_project",
        "verify_cli",
    ]
    assert len(calls) == 3


def test_install_failure_blocks_cli(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        if "pip" in command:
            return completed(
                command,
                returncode=1,
            )
        return completed(command)

    evidence = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    assert evidence.status == "failed"
    assert [
        item.name
        for item in evidence.commands
    ] == [
        "create_venv",
        "install_project",
    ]


def test_venv_failure_stops_pipeline(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            returncode=1,
        )

    evidence = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    assert evidence.status == "failed"
    assert len(evidence.commands) == 1


def test_copy_excludes_local_environment(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )
    local_venv = source / ".venv"
    local_venv.mkdir()
    (
        local_venv / "secret.txt"
    ).write_text(
        "should not copy",
        encoding="utf-8",
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    workspace = (
        tmp_path / "workspace"
    )

    run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
        ),
        runner=runner,
        workspace_root=workspace,
    )

    assert not (
        workspace
        / "project"
        / ".venv"
    ).exists()


def test_project_digest_is_stable(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    first = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "first.json"
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace-1"
        ),
    )
    second = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "second.json"
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace-2"
        ),
    )

    assert (
        first.project_digest
        == second.project_digest
    )


def test_require_clean_environment_raises(
    tmp_path: Path,
) -> None:
    source = source_project(
        tmp_path
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            returncode=1,
        )

    evidence = run_clean_environment(
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
        ),
        runner=runner,
        workspace_root=(
            tmp_path / "workspace"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="create_venv",
    ):
        require_clean_environment(
            evidence
        )


def test_rejects_non_project_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "empty"
    source.mkdir()

    with pytest.raises(
        ValueError,
        match="pyproject.toml",
    ):
        CleanEnvironmentConfig(
            source_root=str(source),
            evidence_path=str(
                tmp_path / "evidence.json"
            ),
        ).validate()
