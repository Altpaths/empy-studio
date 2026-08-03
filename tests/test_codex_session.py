from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from empy_studio.codex_materializer import (
    materialize_codex_run,
)
from empy_studio.codex_session import (
    build_codex_resume_command,
    ensure_evidence_index,
    load_evidence_index,
    resume_codex_run,
)
from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def resumable_manifest(
    tmp_path: Path,
) -> Path:
    project = tmp_path / "project"
    project.mkdir()

    planned = CodexRunManifest(
        run_id="run-001",
        project_root=str(project.resolve()),
        task=CodexTaskContract(
            task_id="ticket-5.5",
            title="Resume Codex",
            objective="Continue a previous Codex thread.",
            acceptance_criteria=(
                "Resume evidence is preserved",
            ),
        ),
        policy=CodexExecutionPolicy(),
    )
    prepared = materialize_codex_run(
        planned,
        tmp_path / "runs",
    )

    manifest_path = (
        Path(prepared.agents_file).parent
        / "manifest.json"
    )
    value = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    value["status"] = "completed"
    value["thread_id"] = "thread-123"
    value["metadata"] = {
        "returncode": 0,
        "event_count": 2,
    }
    manifest_path.write_text(
        json.dumps(value) + "\n",
        encoding="utf-8",
    )

    evidence = Path(prepared.evidence_dir)
    (evidence / "events.jsonl").write_text(
        (
            '{"type":"thread.started",'
            '"thread_id":"thread-123"}\n'
            '{"type":"turn.completed"}\n'
        ),
        encoding="utf-8",
    )
    (evidence / "stderr.log").write_text(
        "",
        encoding="utf-8",
    )
    (evidence / "final-message.md").write_text(
        "Initial result",
        encoding="utf-8",
    )

    return manifest_path


def test_builds_resume_command_with_thread_id(
    tmp_path: Path,
) -> None:
    manifest_path = resumable_manifest(tmp_path)
    value = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    manifest = CodexRunManifest.from_dict(value)

    command = build_codex_resume_command(
        manifest,
        codex_executable="/usr/local/bin/codex",
        final_message_path=tmp_path / "final.md",
    )

    assert command[:3] == [
        "/usr/local/bin/codex",
        "exec",
        "--json",
    ]
    assert command[-3:] == [
        "resume",
        "thread-123",
        "-",
    ]


def test_creates_index_for_initial_evidence(
    tmp_path: Path,
) -> None:
    manifest_path = resumable_manifest(tmp_path)
    manifest = CodexRunManifest.from_dict(
        json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    )

    index = ensure_evidence_index(manifest)

    assert index.run_id == "run-001"
    assert index.thread_id == "thread-123"
    assert len(index.turns) == 1
    assert index.turns[0].kind == "initial"
    assert index.turns[0].event_count == 2


def test_resume_persists_new_evidence_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = resumable_manifest(tmp_path)

    def fake_run(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        final_index = (
            command.index("--output-last-message")
            + 1
        )
        Path(command[final_index]).write_text(
            "Follow-up complete",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"type":"thread.started",'
                '"thread_id":"thread-123"}\n'
                '{"type":"turn.completed"}\n'
            ),
            stderr="resume progress\n",
        )

    monkeypatch.setattr(
        "empy_studio.codex_session.subprocess.run",
        fake_run,
    )

    result = resume_codex_run(
        manifest_path,
        "Review the remaining verification failure.",
    )

    assert result.status == "completed"
    assert result.sequence == 1
    assert result.thread_id == "thread-123"
    assert Path(result.events_path).is_file()

    index = load_evidence_index(
        Path(result.evidence_index).parent
    )
    assert len(index.turns) == 2
    assert index.turns[1].kind == "resume"
    assert index.turns[1].event_count == 2

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"
    assert persisted["metadata"]["resume_sequence"] == 1


def test_second_resume_uses_next_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = resumable_manifest(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_session.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout='{"type":"turn.completed"}\n',
            stderr="",
        ),
    )

    first = resume_codex_run(
        manifest_path,
        "First follow-up",
    )
    second = resume_codex_run(
        manifest_path,
        "Second follow-up",
    )

    assert first.sequence == 1
    assert second.sequence == 2


def test_rejects_resume_without_thread_id(
    tmp_path: Path,
) -> None:
    manifest_path = resumable_manifest(tmp_path)
    value = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    value["thread_id"] = None
    manifest_path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="without thread_id",
    ):
        resume_codex_run(
            manifest_path,
            "Continue",
        )


def test_invalid_resume_jsonl_marks_run_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = resumable_manifest(tmp_path)

    monkeypatch.setattr(
        "empy_studio.codex_session.subprocess.run",
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
        resume_codex_run(
            manifest_path,
            "Continue",
        )

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "failed"
    assert (
        persisted["metadata"]["failure_type"]
        == "resume_invalid_jsonl"
    )


def test_empty_follow_up_is_rejected(
    tmp_path: Path,
) -> None:
    manifest_path = resumable_manifest(tmp_path)

    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        resume_codex_run(
            manifest_path,
            "   ",
        )
