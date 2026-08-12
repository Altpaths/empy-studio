from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from empy_studio import web_desktop
from empy_studio.drivers import CodexDriver
from empy_studio.verification_pipeline import (
    VerificationCheck,
    VerificationReport,
    VerificationResult,
    verification_contract_signature,
)
from empy_studio.web_desktop import GuidedState


class AcceptanceProcess:
    def __init__(self, stdout: str) -> None:
        self.pid = 123_456
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO()

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


class PassingVerificationRuntime:
    def run(
        self,
        *,
        detection: Any,
        evidence_root: Path,
        on_event: Any = None,
        cancel_event: Any = None,
    ) -> VerificationReport:
        del on_event, cancel_event
        evidence_root.mkdir(parents=True, exist_ok=True)
        check = VerificationCheck(
            check_id="acceptance",
            label="Deterministic acceptance check",
            category="tests",
            command=("empy", "t17-acceptance"),
        )
        result = VerificationResult(
            check=check,
            status="pass",
            returncode=0,
            stdout="acceptance ok\n",
            stderr="",
            started_at="2026-08-10T00:00:00+00:00",
            finished_at="2026-08-10T00:00:01+00:00",
        )
        return VerificationReport(
            schema_version=1,
            verification_id="t17-acceptance-verification",
            project_root=str(evidence_root.parent),
            project_type="php",
            status="pass",
            started_at="2026-08-10T00:00:00+00:00",
            finished_at="2026-08-10T00:00:01+00:00",
            results=(result,),
            evidence_path=str(evidence_root),
            contract_signature=verification_contract_signature(detection),
        )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".git", ".empy", "vendor", "storage"}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _php_project(root: Path) -> Path:
    root.mkdir()
    (root / "README.md").write_text(
        "# Acceptance PHP project\n\nOriginal content.\n",
        encoding="utf-8",
    )
    (root / "index.php").write_text(
        "<?php\necho 'ok';\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "App.php").write_text(
        "<?php\nfinal class App {}\n",
        encoding="utf-8",
    )
    (root / "composer.json").write_text(
        json.dumps(
            {
                "name": "empy/t17-acceptance",
                "require": {"php": ">=8.2"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _ready_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    del kwargs
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, "codex-cli t17\n", "")
    if command[-2:] == ["exec", "--help"]:
        return subprocess.CompletedProcess(command, 0, "Usage: codex exec\n", "")
    if command[-2:] == ["login", "status"]:
        return subprocess.CompletedProcess(command, 0, "Logged in\n", "")
    raise AssertionError(command)


def _install_acceptance_driver(
    state: GuidedState,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    assert state.graph is not None
    owned_nodes = [node for node in state.graph.nodes if node.owned_files]
    assert owned_nodes, "the accepted plan must assign a file to an agent"
    owner = owned_nodes[0]
    target_relative = next(
        (
            path
            for path in owner.owned_files
            if not path.endswith("/")
            and (path.startswith("src/") or path.endswith(".php"))
        ),
        next(
            (path for path in owner.owned_files if not path.endswith("/")),
            None,
        ),
    )
    assert target_relative is not None, "the accepted plan must own a file"

    def process_factory(
        command: list[str],
        **kwargs: Any,
    ) -> AcceptanceProcess:
        del kwargs
        final_path = Path(
            command[command.index("--output-last-message") + 1]
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        node_id = final_path.parent.name
        project_root = Path(
            command[command.index("--cd") + 1]
        )
        if node_id == owner.node_id:
            target = project_root / target_relative
            target.write_text(
                target.read_text(encoding="utf-8")
                + "\nEmpy T17 acceptance marker.\n",
                encoding="utf-8",
            )
        final_path.write_text(
            f"Completed deterministic node {node_id}.\n",
            encoding="utf-8",
        )
        events = (
            {
                "type": "thread.started",
                "thread_id": f"t17-{node_id}",
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 24,
                    "cached_input_tokens": 80,
                    "total_tokens": 144,
                },
            },
        )
        return AcceptanceProcess(
            "".join(json.dumps(event) + "\n" for event in events)
        )

    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )
    state.driver = CodexDriver(
        artifact_root=state.workspace_root / "codex-runs",
        command_runner=_ready_runner,
        process_factory=process_factory,
    )
    return target_relative


def _wait_for_run(state: GuidedState) -> None:
    deadline = time.monotonic() + 30
    while state.running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert state.running is False, "Empy run did not reach a terminal state"
    assert state.run is not None
    assert state.run.status == "completed", state.run.error_message
    assert state.verification is not None
    assert state.verification.finalized_at is not None
    assert state.review is not None


def _run_two_ticket_flow(
    source: Path,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_digest = _tree_digest(source)
    monkeypatch.setattr(web_desktop, "VerificationRuntime", PassingVerificationRuntime)

    state = GuidedState(workspace)
    state.import_path(str(source))
    assert state.detection is not None
    assert state.detection.descriptor.project_type == "php"
    project_id = state.active_project_id
    assert project_id is not None
    imported_root = state.detection.descriptor.root
    baseline_readme = (imported_root / "README.md").read_bytes()

    state.create_plan(
        "Implement the requested backend acceptance marker in the PHP source.\n"
        "Do not change configuration, database, or assets."
    )
    state.run_benchmark()
    assert state.benchmark is not None
    assert state.benchmark.saved_tokens > 0
    first_task_id = state.active_task_id
    assert first_task_id is not None
    target_relative = _install_acceptance_driver(state, monkeypatch)
    baseline_target = (imported_root / target_relative).read_bytes()
    state.start_run()
    _wait_for_run(state)

    assert b"Empy T17 acceptance marker" in (
        imported_root / target_relative
    ).read_bytes()
    state.decide_all("accept")
    assert (imported_root / target_relative).read_bytes() != baseline_target
    if target_relative != "README.md":
        assert (imported_root / "README.md").read_bytes() == baseline_readme
    first_archive = tmp_path / "first-release.zip"
    state.export_project(str(first_archive))
    assert state.export is not None
    assert state.export.verified is True
    assert first_archive.is_file()

    reopened = GuidedState(workspace)
    assert reopened.active_project_id == project_id
    assert reopened.active_task_id == first_task_id
    assert reopened.export is not None
    assert reopened.run is not None
    assert reopened.run.status == "completed"
    assert reopened.verification is not None
    assert reopened.verification.finalized_at is not None
    assert reopened.review is not None
    assert reopened.review.pending_count == 0
    reopened.create_plan(
        "Implement the second bounded backend acceptance change in the PHP source.\n"
        "Do not change unrelated project behavior."
    )
    second_task_id = reopened.active_task_id
    assert second_task_id is not None
    second_target_relative = _install_acceptance_driver(reopened, monkeypatch)
    reopened.start_run()
    _wait_for_run(reopened)
    reopened.decide_all("accept")
    second_archive = tmp_path / "second-release.zip"
    reopened.export_project(str(second_archive))
    assert reopened.export is not None
    assert reopened.export.verified is True
    assert second_archive.is_file()
    assert b"Empy T17 acceptance marker" in (
        reopened.detection.descriptor.root / second_target_relative
    ).read_bytes()

    new_source = _php_project(tmp_path / "new-project")
    reopened.reset()
    reopened.import_path(str(new_source))
    new_project_id = reopened.active_project_id
    assert new_project_id is not None
    assert new_project_id != project_id
    assert reopened.active_task_id is None
    projects = reopened.public()["projects"]
    old_record = next(item for item in projects if item["id"] == project_id)
    new_record = next(item for item in projects if item["id"] == new_project_id)
    assert old_record["tasks"]
    assert new_record["tasks"] == []
    assert _tree_digest(source) == original_digest


def test_t17_two_ticket_flow_and_project_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _php_project(tmp_path / "source")
    _run_two_ticket_flow(
        source,
        tmp_path / "empy-workspace",
        tmp_path,
        monkeypatch,
    )


def test_t17_holda_witness_runs_through_empy_without_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = os.environ.get("EMPY_HOLDA_FIXTURE")
    if not configured:
        pytest.skip("set EMPY_HOLDA_FIXTURE for the real Holda witness run")
    source = Path(configured).expanduser().resolve()
    _run_two_ticket_flow(
        source,
        tmp_path / "empy-holda-workspace",
        tmp_path,
        monkeypatch,
    )
