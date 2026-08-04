from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from empy_studio.core import ProductTask


class TaskWorkspaceAdapter:
    """Persist product tasks inside the Empy workspace."""

    def __init__(
        self,
        workspace_root: str | Path,
    ) -> None:
        self.workspace_root = Path(
            workspace_root
        ).expanduser().resolve()
        self.workspace_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path = (
            self.workspace_root
            / "product-tasks.json"
        )

    def save_task(
        self,
        task: ProductTask,
    ) -> None:
        task.validate()
        existing = {
            item["task_id"]: item
            for item in self._read()
        }
        existing[task.task_id] = asdict(task)
        self.path.write_text(
            json.dumps(
                list(existing.values()),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def list_tasks(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[ProductTask, ...]:
        values = self._read()
        if project_root is not None:
            values = [
                item
                for item in values
                if item.get("project_root")
                == project_root
            ]

        return tuple(
            ProductTask(
                task_id=str(item["task_id"]),
                project_root=str(
                    item["project_root"]
                ),
                kind=str(
                    item["kind"]
                ),  # type: ignore[arg-type]
                title=str(item["title"]),
                objective=str(
                    item["objective"]
                ),
                requirements=tuple(
                    str(value)
                    for value in item.get(
                        "requirements",
                        [],
                    )
                ),
                constraints=tuple(
                    str(value)
                    for value in item.get(
                        "constraints",
                        [],
                    )
                ),
                definition_of_done=tuple(
                    str(value)
                    for value in item.get(
                        "definition_of_done",
                        [],
                    )
                ),
                status=str(
                    item.get(
                        "status",
                        "draft",
                    )
                ),
            )
            for item in values
        )

    def _read(
        self,
    ) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, dict)
        ]
