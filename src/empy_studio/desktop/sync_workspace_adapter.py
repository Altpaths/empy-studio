from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.core.sync_resolver import (
    AgentPatch,
    ConflictKind,
    PatchOperation,
    PatchQueueItem,
    PatchState,
    ResolutionChoice,
    SyncConflict,
    SyncReport,
    SyncStatus,
    apply_sync_report,
    resolve_sync_conflict,
)


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise TypeError(f"{field} must be an integer") from exc
    raise TypeError(f"{field} must be an integer")


def _as_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    return tuple(str(entry) for entry in value)


class SyncWorkspaceAdapter:
    """Persist and operate sync reports for Desktop conflict review."""

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

    def load(self, sync_id: str) -> SyncReport:
        return self._from_dict(self.raw(sync_id))

    def list_reports(self) -> tuple[SyncReport, ...]:
        return tuple(self.load(path.stem) for path in sorted(self.root.glob("*.json")))

    def resolve(
        self,
        sync_id: str,
        *,
        conflict_id: str,
        choice: str,
        manual_content: str | None = None,
    ) -> SyncReport:
        report = resolve_sync_conflict(
            self.load(sync_id),
            conflict_id=conflict_id,
            choice=cast(ResolutionChoice, choice),
            manual_content=manual_content,
        )
        self.save(report)
        return report

    def apply(self, sync_id: str) -> SyncReport:
        report = apply_sync_report(self.load(sync_id))
        self.save(report)
        return report

    @staticmethod
    def _from_dict(value: dict[str, object]) -> SyncReport:
        queue_values = value.get("queue", [])
        conflict_values = value.get("conflicts", [])
        if not isinstance(queue_values, list) or not isinstance(conflict_values, list):
            raise TypeError("sync report queue and conflicts must be lists")

        queue: list[PatchQueueItem] = []
        for item in queue_values:
            if not isinstance(item, dict) or not isinstance(item.get("patch"), dict):
                raise TypeError("invalid patch queue item")
            raw_patch = cast(dict[str, object], item["patch"])
            patch = AgentPatch(
                patch_id=str(raw_patch["patch_id"]),
                node_id=str(raw_patch["node_id"]),
                agent_id=str(raw_patch["agent_id"]),
                step_id=str(raw_patch["step_id"]),
                relative_path=str(raw_patch["relative_path"]),
                operation=cast(PatchOperation, str(raw_patch["operation"])),
                base_sha256=(str(raw_patch["base_sha256"]) if raw_patch.get("base_sha256") is not None else None),
                content=(str(raw_patch["content"]) if raw_patch.get("content") is not None else None),
                created_at=str(raw_patch["created_at"]),
                sequence=_as_int(raw_patch.get("sequence", 0), "patch.sequence"),
            )
            raw_ids = item.get("conflict_ids", [])
            queue.append(
                PatchQueueItem(
                    patch=patch,
                    state=cast(PatchState, str(item["state"])),
                    order=_as_int(item["order"], "queue.order"),
                    conflict_ids=_as_string_tuple(raw_ids, "queue.conflict_ids"),
                )
            )

        conflicts: list[SyncConflict] = []
        for item in conflict_values:
            if not isinstance(item, dict):
                raise TypeError("invalid sync conflict")
            raw_competing = item.get("competing_patch_ids", [])
            conflicts.append(
                SyncConflict(
                    conflict_id=str(item["conflict_id"]),
                    patch_id=str(item["patch_id"]),
                    relative_path=str(item["relative_path"]),
                    kind=cast(ConflictKind, str(item["kind"])),
                    message=str(item["message"]),
                    current_sha256=(str(item["current_sha256"]) if item.get("current_sha256") is not None else None),
                    expected_sha256=(str(item["expected_sha256"]) if item.get("expected_sha256") is not None else None),
                    competing_patch_ids=_as_string_tuple(raw_competing, "conflict.competing_patch_ids"),
                    resolution=cast(ResolutionChoice | None, item.get("resolution")),
                    manual_content=(str(item["manual_content"]) if item.get("manual_content") is not None else None),
                    resolved_at=(str(item["resolved_at"]) if item.get("resolved_at") is not None else None),
                )
            )

        report = SyncReport(
            schema_version=_as_int(value["schema_version"], "schema_version"),
            sync_id=str(value["sync_id"]),
            graph_id=str(value["graph_id"]),
            project_root=str(value["project_root"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            status=cast(SyncStatus, str(value["status"])),
            queue=tuple(queue),
            conflicts=tuple(conflicts),
            applied_patch_ids=_as_string_tuple(value.get("applied_patch_ids", []), "applied_patch_ids"),
            skipped_patch_ids=_as_string_tuple(value.get("skipped_patch_ids", []), "skipped_patch_ids"),
        )
        report.validate()
        return report
