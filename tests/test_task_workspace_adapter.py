from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    ProductTask,
)
from empy_studio.desktop.task_workspace_adapter import (
    TaskWorkspaceAdapter,
)


def test_persists_product_task(
    tmp_path: Path,
) -> None:
    store = TaskWorkspaceAdapter(
        tmp_path / "workspace"
    )
    task = ProductTask(
        task_id="task-1",
        project_root="/tmp/project",
        kind="custom",
        title="Task",
        objective="Objective",
        requirements=("Requirement",),
        constraints=(),
        definition_of_done=("Done",),
        status="ready_for_planning",
    )

    store.save_task(task)

    loaded = store.list_tasks(
        project_root="/tmp/project"
    )
    assert loaded == (task,)
