from __future__ import annotations

from pathlib import Path

from empy_studio.core import SyncReport
from empy_studio.desktop.sync_workspace_adapter import SyncWorkspaceAdapter


def test_persists_sync_report_for_conflict_ui(tmp_path: Path) -> None:
    report = SyncReport(
        schema_version=1,
        sync_id="sync-one",
        graph_id="graph-one",
        project_root=str(tmp_path),
        created_at="2026-08-04T00:00:00+00:00",
        updated_at="2026-08-04T00:00:00+00:00",
        status="ready",
        queue=(),
        conflicts=(),
    )
    adapter = SyncWorkspaceAdapter(tmp_path / "workspace")
    path = adapter.save(report)
    assert path.is_file()
    assert adapter.raw("sync-one")["status"] == "ready"
    assert len(adapter.list_reports()) == 1


def test_loads_and_resolves_persisted_conflict(tmp_path: Path) -> None:
    from empy_studio.core import AgentPatch, PatchQueueItem, SyncConflict

    patch = AgentPatch(
        patch_id="patch-one",
        node_id="node-one",
        agent_id="agent-one",
        step_id="step-one",
        relative_path="app.txt",
        operation="modify",
        base_sha256="old",
        content="new",
        created_at="2026-08-05T00:00:00+00:00",
    )
    conflict = SyncConflict(
        conflict_id="conflict-one",
        patch_id="patch-one",
        relative_path="app.txt",
        kind="stale-base",
        message="changed",
        current_sha256="current",
        expected_sha256="old",
    )
    report = SyncReport(
        schema_version=1,
        sync_id="sync-conflict",
        graph_id="graph-one",
        project_root=str(tmp_path),
        created_at="2026-08-05T00:00:00+00:00",
        updated_at="2026-08-05T00:00:00+00:00",
        status="blocked",
        queue=(PatchQueueItem(patch=patch, state="conflict", order=1, conflict_ids=("conflict-one",)),),
        conflicts=(conflict,),
    )
    adapter = SyncWorkspaceAdapter(tmp_path / "workspace")
    adapter.save(report)

    loaded = adapter.load("sync-conflict")
    assert loaded.conflicts[0].kind == "stale-base"
    resolved = adapter.resolve(
        "sync-conflict",
        conflict_id="conflict-one",
        choice="keep-current",
    )
    assert resolved.status == "ready"
    assert resolved.queue[0].state == "skipped"
