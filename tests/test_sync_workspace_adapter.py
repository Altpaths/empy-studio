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
