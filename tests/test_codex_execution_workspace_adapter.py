from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from empy_studio.core import (
    ContextManifest,
    ContextManifestFile,
    LedgerEntry,
    RouteAttempt,
    RouteReport,
    TaskLedgerSnapshot,
)
from empy_studio.desktop.codex_execution_workspace_adapter import (
    CodexExecutionWorkspaceAdapter,
)
from empy_studio.drivers import (
    CodexGraphExecution,
    CodexInstallation,
    CodexNodeExecution,
    CodexProgressEvent,
    CodexWaveExecution,
)
from empy_studio.token_usage import TokenUsage


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
        usage=TokenUsage(
            input=12,
            output=5,
            cached=3,
            total=17,
            source="provider",
            provider="codex",
        ),
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
        usage=TokenUsage(
            input=12,
            output=5,
            cached=3,
            total=17,
            source="provider",
            provider="codex",
        ),
        schedule=(
            CodexWaveExecution(
                wave=1,
                node_ids=("node-1",),
                mode="serial",
                capacity=1,
                started_at="2026-08-04T00:00:00+00:00",
                finished_at="2026-08-04T00:00:01+00:00",
            ),
        ),
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


def test_round_trip_persists_context_ledger_and_route_evidence(tmp_path: Path) -> None:
    adapter = CodexExecutionWorkspaceAdapter(tmp_path / "workspace")
    run = replace(
        sample_run(tmp_path),
        prompt_estimates=(("node-1", 42),),
        context_manifest=ContextManifest(
            schema_version=1,
            project_root=str(tmp_path.resolve()),
            selection_id="selection-11",
            snapshot_sha256="b" * 64,
            files=(
                ContextManifestFile(
                    relative_path="src/example.py",
                    sha256="a" * 64,
                    selected_bytes=12,
                    content_included=True,
                ),
            ),
            selected_bytes=12,
        ),
        task_ledger=TaskLedgerSnapshot(
            schema_version=1,
            total_limit_tokens=100,
            fixed_commitment_tokens=10,
            charged_tokens=20,
            reserved_tokens=0,
            remaining_tokens=70,
            usage_complete=True,
            entries=(
                LedgerEntry(
                    operation_id="node-1",
                    provider_id="codex",
                    reserved_tokens=40,
                    charged_tokens=20,
                    usage_state="reported",
                    fresh_tokens=9,
                    cached_tokens=3,
                    total_tokens=12,
                    status="completed",
                ),
            ),
        ),
        route_report=RouteReport(
            attempts=(
                RouteAttempt(
                    provider_id="codex",
                    model=None,
                    attempt=1,
                    status="completed",
                    usage=TokenUsage(input=12, output=5, cached=3, total=17, source="provider", provider="codex"),
                    usage_state="reported",
                ),
            ),
            selected_provider_id="codex",
            reason="Route completed.",
        ),
    )
    adapter.save_run(run)

    restored = CodexExecutionWorkspaceAdapter(tmp_path / "workspace").get_run(run.run_id)

    assert restored == run


def test_loads_legacy_run_json_without_usage(tmp_path: Path) -> None:
    adapter = CodexExecutionWorkspaceAdapter(tmp_path / "workspace")
    run = sample_run(tmp_path)
    payload = run.to_dict()
    payload.pop("usage", None)
    for node in payload["node_results"]:
        if isinstance(node, dict):
            node.pop("usage", None)
    adapter.path.write_text(
        json.dumps([payload], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    loaded = adapter.get_run(run.run_id)

    assert loaded is not None
    assert loaded.usage is None
    assert loaded.node_results[0].usage is None


def test_round_trip_persists_host_readiness_error_code(tmp_path: Path) -> None:
    adapter = CodexExecutionWorkspaceAdapter(tmp_path / "workspace")
    ready = sample_run(tmp_path)
    run = replace(
        ready,
        status="unavailable",
        installation=replace(
            ready.installation,
            availability="unavailable",
            message="Codex host preflight is unavailable.",
            remediation="Fix the host permissions and refresh.",
            error_code="sandbox_error",
        ),
        node_results=(),
        usage=None,
        error_code="sandbox_error",
        error_message="Codex host preflight is unavailable.",
    )

    adapter.save_run(run)
    loaded = adapter.get_run(run.run_id)

    assert loaded == run
    assert loaded is not None
    assert loaded.installation.error_code == "sandbox_error"


def test_provider_budget_survives_restart_without_turning_unknown_into_zero(tmp_path: Path) -> None:
    from empy_studio.core.token_budget import ProviderBudgetReport, ProviderNodeBudgetReport

    run = replace(sample_run(tmp_path), budget_accounting=ProviderBudgetReport(
        budget_id="budget", planned_total_limit_tokens=100,
        nodes=(ProviderNodeBudgetReport(node_id="node-1", step_id="step-1",
               planned_limit_tokens=90, effective_fresh_limit_tokens=90,
               cap_source="locked", executed=True),),
    ))
    store = CodexExecutionWorkspaceAdapter(tmp_path / "execution.json")
    store.save_run(run)
    restored = CodexExecutionWorkspaceAdapter(tmp_path / "execution.json").get_run(run.run_id)
    assert restored is not None
    assert restored.budget_accounting == run.budget_accounting
    report = restored.to_dict()["budget_accounting"]
    assert report["usage_complete"] is False
    assert report["unknown_usage_node_ids"] == ["node-1"]
