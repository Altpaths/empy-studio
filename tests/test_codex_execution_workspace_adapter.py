from __future__ import annotations

from pathlib import Path

from empy_studio.desktop.codex_execution_workspace_adapter import (
    CodexExecutionWorkspaceAdapter,
)
from empy_studio.drivers import (
    CodexGraphExecution,
    CodexInstallation,
    CodexNodeExecution,
    CodexProgressEvent,
)


def sample_run(tmp_path: Path) -> CodexGraphExecution:
    node_dir = tmp_path / "runs" / "run-11" / "nodes" / "node-1"
    node = CodexNodeExecution(
        node_id="node-1",
        task_id="task-11:step-1",
        status="completed",
        started_at="2026-08-04T00:00:00+00:00",
        finished_at="2026-08-04T00:00:01+00:00",
        return_code=0,
        thread_id="thread-11",
        summary="Completed",
        changed_files=("src/example.py",),
        event_count=1,
        events_path=str(node_dir / "events.jsonl"),
        stderr_path=str(node_dir / "stderr.log"),
        final_message_path=str(node_dir / "final-message.md"),
        command_path=str(node_dir / "command.json"),
    )
    event = CodexProgressEvent(
        timestamp="2026-08-04T00:00:00+00:00",
        level="info",
        event_type="thread.started",
        message="Codex session started.",
        node_id="node-1",
    )
    run = CodexGraphExecution(
        schema_version=1,
        run_id="run-11",
        graph_id="graph-11",
        task_id="task-11",
        project_root=str(tmp_path.resolve()),
        provider="codex",
        status="completed",
        started_at="2026-08-04T00:00:00+00:00",
        finished_at="2026-08-04T00:00:01+00:00",
        installation=CodexInstallation(
            availability="available",
            executable="/usr/local/bin/codex",
            version="codex-cli 1.2.3",
            authenticated=True,
            message="ready",
        ),
        node_results=(node,),
        events=(event,),
    )
    run.validate()
    return run


def test_round_trip_persists_run_evidence(tmp_path: Path) -> None:
    adapter = CodexExecutionWorkspaceAdapter(tmp_path / "workspace")
    run = sample_run(tmp_path)

    adapter.save_run(run)
    loaded = adapter.get_run(run.run_id)

    assert loaded == run
    assert adapter.get_for_graph("graph-11") == run
    assert adapter.list_runs() == (run,)
    assert adapter.path.is_file()
