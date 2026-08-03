from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.codex_materializer import materialize_codex_run
from empy_studio.codex_runtime import (
    codex_run_status,
    create_manual_handoff,
    run_codex_workflow,
)
from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def prepared_manifest(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    prepared = materialize_codex_run(
        CodexRunManifest(
            run_id="run-001",
            project_root=str(project.resolve()),
            task=CodexTaskContract(
                task_id="ticket-5.6",
                title="Runtime integration",
                objective="Dispatch one Codex workflow.",
                acceptance_criteria=("Dispatch is explicit",),
            ),
            policy=CodexExecutionPolicy(),
        ),
        tmp_path / "runs",
    )
    return Path(prepared.agents_file).parent / "manifest.json"


def test_not_ready_creates_manual_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = prepared_manifest(tmp_path)
    monkeypatch.setattr(
        "empy_studio.codex_runtime.diagnose_codex_environment",
        lambda *args, **kwargs: {"status": "not_ready", "checks": []},
    )
    result = run_codex_workflow(manifest)
    assert result.status == "manual_required"
    assert result.mode == "manual"
    persisted = json.loads(manifest.read_text(encoding="utf-8"))
    assert persisted["status"] == "manual_required"


def test_ready_dispatches_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = prepared_manifest(tmp_path)
    monkeypatch.setattr(
        "empy_studio.codex_runtime.diagnose_codex_environment",
        lambda *args, **kwargs: {"status": "ready", "checks": []},
    )

    class Result:
        status = "completed"
        run_id = "run-001"

        def to_dict(self):
            return {"status": self.status}

    monkeypatch.setattr(
        "empy_studio.codex_runtime.execute_codex_run",
        lambda *args, **kwargs: Result(),
    )
    result = run_codex_workflow(manifest)
    assert result.mode == "execute"


def test_completed_dispatches_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = prepared_manifest(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["status"] = "completed"
    value["thread_id"] = "thread-123"
    manifest.write_text(json.dumps(value), encoding="utf-8")

    class Result:
        status = "completed"
        run_id = "run-001"

        def to_dict(self):
            return {"status": self.status}

    monkeypatch.setattr(
        "empy_studio.codex_runtime.resume_codex_run",
        lambda *args, **kwargs: Result(),
    )
    result = run_codex_workflow(
        manifest,
        follow_up_prompt="Continue",
    )
    assert result.mode == "resume"


def test_resume_requires_prompt(tmp_path: Path) -> None:
    manifest = prepared_manifest(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["status"] = "completed"
    value["thread_id"] = "thread-123"
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="follow_up_prompt"):
        run_codex_workflow(manifest)


def test_status_returns_state(tmp_path: Path) -> None:
    manifest = prepared_manifest(tmp_path)
    result = codex_run_status(manifest)
    assert result["status"] == "prepared"


def test_explicit_manual_handoff(tmp_path: Path) -> None:
    manifest = prepared_manifest(tmp_path)
    handoff = create_manual_handoff(
        manifest,
        reason="User selected manual mode",
    )
    assert handoff["status"] == "manual_required"
