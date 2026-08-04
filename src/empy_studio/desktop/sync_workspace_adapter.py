from __future__ import annotations

import json
from pathlib import Path

from empy_studio.core.sync_resolver import SyncReport


class SyncWorkspaceAdapter:
    """Persist immutable sync reports for Desktop conflict review."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve() / "sync-reports"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, report: SyncReport) -> Path:
        report.validate()
        destination = self.root / f"{report.sync_id}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def raw(self, sync_id: str) -> dict[str, object]:
        path = self.root / f"{sync_id}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("sync report must contain an object")
        return value

    def list_reports(self) -> tuple[dict[str, object], ...]:
        return tuple(self.raw(path.stem) for path in sorted(self.root.glob("*.json")))
