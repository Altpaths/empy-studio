from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    generate_execution_plan,
)
from empy_studio.desktop.plan_workspace_adapter import (
    PlanWorkspaceAdapter,
)


def test_persists_execution_plan(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (
        project
        / "pyproject.toml"
    ).write_text(
        "[project]\nname='demo'\n",
        encoding="utf-8",
    )

    task = ProductTask(
        task_id="task-1",
        project_root=str(
            project.resolve()
        ),
        kind="custom",
        title="Task",
        objective="Improve module",
        requirements=("Change module",),
        constraints=(),
        definition_of_done=("Tests pass",),
        status="ready_for_planning",
    )
    detection = (
        DefaultProjectService()
        .detect(project)
    )
    plan = generate_execution_plan(
        task=task,
        project=detection,
    )

    store = PlanWorkspaceAdapter(
        tmp_path / "workspace"
    )
    store.save_plan(plan)

    loaded = store.get_for_task(
        "task-1"
    )
    assert loaded == plan
