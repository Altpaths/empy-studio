from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from empy_studio.codex_doctor import (
    diagnose_codex_environment,
)


def create_materialized_run(
    tmp_path: Path,
) -> Path:
    project = tmp_path / "project"
    project.mkdir()

    run = tmp_path / "run"
    evidence = run / "evidence"
    evidence.mkdir(parents=True)

    agents = run / "AGENTS.md"
    prompt = run / "prompt.md"
    agents.write_text("instructions", encoding="utf-8")
    prompt.write_text("task", encoding="utf-8")

    manifest = run / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "project_root": str(project.resolve()),
                "task": {
                    "task_id": "ticket-5.3",
                    "title": "Diagnose Codex",
                    "objective": "Check the Codex environment.",
                    "acceptance_criteria": [
                        "Installation is detected"
                    ],
                },
                "policy": {},
                "agents_file": str(agents),
                "prompt_file": str(prompt),
                "evidence_dir": str(evidence),
                "status": "prepared",
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    return manifest


class FakeResult:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_ready_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_materialized_run(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_doctor.shutil.which",
        lambda executable: "/usr/local/bin/codex",
    )

    def fake_run(
        command: Any,
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 10.0,
    ) -> FakeResult:
        if command[-1] == "--version":
            return FakeResult(
                stdout="codex-cli 1.0.0"
            )
        if command[:2] == [
            "/usr/local/bin/codex",
            "exec",
        ]:
            return FakeResult(
                stdout="Usage: codex exec"
            )
        if command[-2:] == ["login", "status"]:
            return FakeResult(
                stdout="Logged in with ChatGPT"
            )
        if command[:2] == ["git", "rev-parse"]:
            return FakeResult(
                stdout=str(tmp_path / "project")
            )
        if command[:2] == ["git", "status"]:
            return FakeResult(stdout="")
        raise AssertionError(command)

    monkeypatch.setattr(
        "empy_studio.codex_doctor._run_command",
        fake_run,
    )

    result = diagnose_codex_environment(manifest)

    assert result["status"] == "ready"
    assert result["failed_check_count"] == 0


def test_missing_codex_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_materialized_run(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_doctor.shutil.which",
        lambda executable: None,
    )
    monkeypatch.setattr(
        "empy_studio.codex_doctor._check_git_repository",
        lambda manifest: [],
    )

    result = diagnose_codex_environment(manifest)

    assert result["status"] == "not_ready"
    assert any(
        check["check_id"] == "codex_executable"
        and check["status"] == "failed"
        for check in result["checks"]
    )


def test_unauthenticated_codex_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_materialized_run(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_doctor.shutil.which",
        lambda executable: "/usr/local/bin/codex",
    )

    def fake_run(
        command: Any,
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 10.0,
    ) -> FakeResult:
        if command[-1] == "--version":
            return FakeResult(stdout="codex-cli 1.0.0")
        if command[:2] == [
            "/usr/local/bin/codex",
            "exec",
        ]:
            return FakeResult(stdout="Usage: codex exec")
        if command[-2:] == ["login", "status"]:
            return FakeResult(
                returncode=1,
                stderr="Not logged in",
            )
        if command[:2] == ["git", "rev-parse"]:
            return FakeResult(returncode=1)
        raise AssertionError(command)

    monkeypatch.setattr(
        "empy_studio.codex_doctor._run_command",
        fake_run,
    )

    result = diagnose_codex_environment(manifest)

    assert result["status"] == "not_ready"
    assert any(
        check["check_id"] == "codex_authentication"
        and check["status"] == "failed"
        for check in result["checks"]
    )


def test_missing_materialized_file_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_materialized_run(tmp_path)
    value = json.loads(
        manifest.read_text(encoding="utf-8")
    )
    Path(value["prompt_file"]).unlink()

    monkeypatch.setattr(
        "empy_studio.codex_doctor.shutil.which",
        lambda executable: None,
    )
    monkeypatch.setattr(
        "empy_studio.codex_doctor._check_git_repository",
        lambda manifest: [],
    )

    result = diagnose_codex_environment(manifest)

    assert any(
        check["check_id"] == "prompt_file"
        and check["status"] == "failed"
        for check in result["checks"]
    )


def test_dirty_git_worktree_is_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_materialized_run(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_doctor.shutil.which",
        lambda executable: None,
    )

    def fake_run(
        command: Any,
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 10.0,
    ) -> FakeResult:
        if command[:2] == ["git", "rev-parse"]:
            return FakeResult(
                stdout=str(tmp_path / "project")
            )
        if command[:2] == ["git", "status"]:
            return FakeResult(
                stdout=" M src/example.py\n"
            )
        raise AssertionError(command)

    monkeypatch.setattr(
        "empy_studio.codex_doctor._run_command",
        fake_run,
    )

    result = diagnose_codex_environment(manifest)

    assert result["warning_count"] == 1
    assert any(
        check["check_id"] == "git_worktree"
        and check["status"] == "warning"
        for check in result["checks"]
    )


def test_timeout_must_be_positive(
    tmp_path: Path,
) -> None:
    manifest = create_materialized_run(tmp_path)

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        diagnose_codex_environment(
            manifest,
            command_timeout_seconds=0,
        )
