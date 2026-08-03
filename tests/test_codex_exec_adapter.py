from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from empy_studio.codex_exec_adapter import (
    build_codex_exec_command,
    execute_codex_run,
)
from empy_studio.codex_materializer import materialize_codex_run
from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def prepared_manifest(
    tmp_path: Path,
    *,
    policy: CodexExecutionPolicy | None = None,
) -> Path:
    project = tmp_path / "project"
    project.mkdir()

    manifest = CodexRunManifest(
        run_id="run-001",
        project_root=str(project.resolve()),
        task=CodexTaskContract(
            task_id="ticket-5.4",
            title="Execute Codex",
            objective="Run one bounded Codex task.",
            acceptance_criteria=("Evidence is preserved",),
        ),
        policy=policy or CodexExecutionPolicy(),
    )
    prepared = materialize_codex_run(
        manifest,
        tmp_path / "runs",
    )
    return Path(prepared.agents_file).parent / "manifest.json"


def test_builds_explicit_bounded_command(
    tmp_path: Path,
) -> None:
    manifest_path = prepared_manifest(tmp_path)
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    from empy_studio.codex_workflow import CodexRunManifest

    command = build_codex_exec_command(
        CodexRunManifest.from_dict(manifest),
        codex_executable="/usr/local/bin/codex",
        final_message_path=tmp_path / "final.md",
    )

    assert command[:3] == [
        "/usr/local/bin/codex",
        "exec",
        "--json",
    ]
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--ask-for-approval" in command
    assert "never" in command
    assert command[-1] == "-"


def test_executes_and_persists_jsonl_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = prepared_manifest(tmp_path)

    def fake_run(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        final_index = command.index("--output-last-message") + 1
        Path(command[final_index]).write_text(
            "Completed task",
            encoding="utf-8",
        )
        stdout = (
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            '{"type":"turn.completed"}\n'
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout,
            stderr="progress\n",
        )

    monkeypatch.setattr(
        "empy_studio.codex_exec_adapter.subprocess.run",
        fake_run,
    )

    result = execute_codex_run(
        manifest_path,
        codex_executable="/usr/local/bin/codex",
    )

    assert result.status == "completed"
    assert result.thread_id == "thread-123"
    assert result.event_count == 2
    assert Path(result.events_path).is_file()
    assert Path(result.stderr_path).read_text(
        encoding="utf-8"
    ) == "progress\n"

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"
    assert persisted["thread_id"] == "thread-123"


def test_nonzero_exit_marks_run_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = prepared_manifest(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_exec_adapter.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            2,
            stdout='{"type":"turn.failed"}\n',
            stderr="failure\n",
        ),
    )

    result = execute_codex_run(manifest_path)

    assert result.status == "failed"
    assert result.returncode == 2

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"


def test_invalid_jsonl_marks_run_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = prepared_manifest(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_exec_adapter.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="not-json\n",
            stderr="",
        ),
    )

    with pytest.raises(
        ValueError,
        match="Invalid Codex JSONL",
    ):
        execute_codex_run(manifest_path)

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"
    assert (
        persisted["metadata"]["failure_type"]
        == "invalid_jsonl"
    )


def test_timeout_marks_run_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = prepared_manifest(
        tmp_path,
        policy=CodexExecutionPolicy(timeout_seconds=5),
    )

    def timeout(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            timeout=5,
            stderr="timed out",
        )

    monkeypatch.setattr(
        "empy_studio.codex_exec_adapter.subprocess.run",
        timeout,
    )

    with pytest.raises(
        RuntimeError,
        match="timed out",
    ):
        execute_codex_run(manifest_path)

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"
    assert (
        persisted["metadata"]["failure_type"]
        == "timeout"
    )


def test_rejects_non_prepared_run(
    tmp_path: Path,
) -> None:
    manifest_path = prepared_manifest(tmp_path)
    value = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    value["status"] = "completed"
    manifest_path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Only prepared",
    ):
        execute_codex_run(manifest_path)
