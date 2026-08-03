from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from empy_studio.codex_materializer import materialize_codex_run
from empy_studio.codex_runtime import run_codex_workflow
from empy_studio.codex_session import load_evidence_index
from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def test_complete_codex_workflow_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    manifest = CodexRunManifest(
        run_id="run-e2e",
        project_root=str(project.resolve()),
        task=CodexTaskContract(
            task_id="ticket-5.7",
            title="Complete Codex lifecycle",
            objective=(
                "Verify preparation, execution, resume, "
                "and evidence persistence."
            ),
            acceptance_criteria=(
                "Initial run completes",
                "Resume completes",
                "Evidence index contains both turns",
            ),
            allowed_paths=("src/", "tests/"),
            forbidden_paths=(".env",),
            verification_commands=(
                "python -m pytest -q",
            ),
        ),
        policy=CodexExecutionPolicy(),
    )

    prepared = materialize_codex_run(
        manifest,
        tmp_path / "runs",
    )
    manifest_path = (
        Path(prepared.agents_file).parent
        / "manifest.json"
    )

    monkeypatch.setattr(
        "empy_studio.codex_runtime.diagnose_codex_environment",
        lambda *args, **kwargs: {
            "status": "ready",
            "failed_check_count": 0,
            "warning_count": 0,
            "checks": [],
        },
    )

    call_count = 0

    def fake_run(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1

        final_index = (
            command.index("--output-last-message")
            + 1
        )
        Path(command[final_index]).write_text(
            (
                "Initial completion"
                if call_count == 1
                else "Resume completion"
            ),
            encoding="utf-8",
        )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"type":"thread.started",'
                '"thread_id":"thread-e2e"}\n'
                '{"type":"turn.completed"}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "empy_studio.codex_exec_adapter.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "empy_studio.codex_session.subprocess.run",
        fake_run,
    )

    initial = run_codex_workflow(
        manifest_path,
        codex_executable="/usr/local/bin/codex",
    )

    assert initial.status == "completed"
    assert initial.mode == "execute"

    resumed = run_codex_workflow(
        manifest_path,
        follow_up_prompt="Review the completed change.",
        codex_executable="/usr/local/bin/codex",
    )

    assert resumed.status == "completed"
    assert resumed.mode == "resume"

    persisted = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"
    assert persisted["thread_id"] == "thread-e2e"
    assert persisted["metadata"]["resume_sequence"] == 1

    evidence_dir = Path(persisted["evidence_dir"])
    index = load_evidence_index(evidence_dir)

    assert len(index.turns) == 2
    assert index.turns[0].kind == "initial"
    assert index.turns[1].kind == "resume"
    assert index.turns[1].sequence == 1
    assert call_count == 2
