from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.core import (
    ContextExclusion,
    ContextFile,
    ContextPack,
    ContextSelection,
    ProjectBrain,
)


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


class ContextWorkspaceAdapter:
    """Persist bounded context selections for approved plans."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace_root / "context-selections.json"

    def save_selection(self, selection: ContextSelection) -> None:
        selection.validate()
        existing = {
            str(item["selection_id"]): item
            for item in self._read()
            if "selection_id" in item
        }
        existing[selection.selection_id] = selection.to_dict()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get_for_plan(self, plan_id: str) -> ContextSelection | None:
        matches = [item for item in self._read() if item.get("plan_id") == plan_id]
        if not matches:
            return None
        return self._from_dict(matches[-1])

    def list_selections(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[ContextSelection, ...]:
        values = self._read()
        if project_root is not None:
            values = [item for item in values if item.get("project_root") == project_root]
        return tuple(self._from_dict(item) for item in values)

    def _from_dict(self, value: dict[str, object]) -> ContextSelection:
        brain_value = cast(dict[str, object], value["project_brain"])
        raw_packs = cast(list[object], value.get("packs", []))
        raw_exclusions = cast(list[object], value.get("exclusions", []))

        packs: list[ContextPack] = []
        for raw_pack in raw_packs:
            if not isinstance(raw_pack, dict):
                continue
            raw_files = cast(list[object], raw_pack.get("files", []))
            files: list[ContextFile] = []
            for raw_file in raw_files:
                if not isinstance(raw_file, dict):
                    continue
                files.append(
                    ContextFile(
                        relative_path=str(raw_file["relative_path"]),
                        score=int(raw_file["score"]),
                        reasons=tuple(str(item) for item in cast(list[object], raw_file.get("reasons", []))),
                        size_bytes=int(raw_file["size_bytes"]),
                        included_bytes=int(raw_file["included_bytes"]),
                        sha256=str(raw_file["sha256"]),
                        truncated=bool(raw_file["truncated"]),
                        content=str(raw_file["content"]),
                    )
                )
            packs.append(
                ContextPack(
                    pack_id=str(raw_pack["pack_id"]),
                    plan_id=str(raw_pack["plan_id"]),
                    task_id=str(raw_pack["task_id"]),
                    step_id=str(raw_pack["step_id"]),
                    agent_role=cast(str, raw_pack["agent_role"]),  # type: ignore[arg-type]
                    objective=str(raw_pack["objective"]),
                    files=tuple(files),
                    total_bytes=int(raw_pack["total_bytes"]),
                    candidate_count=int(raw_pack["candidate_count"]),
                )
            )

        exclusions = tuple(
            ContextExclusion(
                relative_path=str(raw["relative_path"]),
                reason=str(raw["reason"]),
                protected=bool(raw["protected"]),
            )
            for raw in raw_exclusions
            if isinstance(raw, dict)
        )
        selection = ContextSelection(
            schema_version=_as_int(
                value["schema_version"],
                "schema_version",
            ),
            selection_id=str(value["selection_id"]),
            plan_id=str(value["plan_id"]),
            task_id=str(value["task_id"]),
            project_root=str(value["project_root"]),
            created_at=str(value["created_at"]),
            project_brain=ProjectBrain(
                project_root=str(brain_value["project_root"]),
                display_name=str(brain_value["display_name"]),
                project_type=str(brain_value["project_type"]),
                markers=tuple(str(item) for item in cast(list[object], brain_value.get("markers", []))),
                package_manager=(
                    str(brain_value["package_manager"])
                    if brain_value.get("package_manager") is not None
                    else None
                ),
                has_git=bool(brain_value["has_git"]),
                has_tests=bool(brain_value["has_tests"]),
                summary=str(brain_value["summary"]),
            ),
            packs=tuple(packs),
            exclusions=exclusions,
            scanned_candidates=_as_int(
                value["scanned_candidates"],
                "scanned_candidates",
            ),
            selected_files=_as_int(
                value["selected_files"],
                "selected_files",
            ),
            selected_bytes=_as_int(
                value["selected_bytes"],
                "selected_bytes",
            ),
        )
        selection.validate()
        return selection

    def _read(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
