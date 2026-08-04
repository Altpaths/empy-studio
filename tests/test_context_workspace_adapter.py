from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    generate_execution_plan,
)
from empy_studio.desktop.context_workspace_adapter import ContextWorkspaceAdapter


def _selection(project_root: Path):
    (project_root / "pyproject.toml").write_text(
        '[project]\nname="demo"\n',
        encoding="utf-8",
    )
    (project_root / "src").mkdir()
    (project_root / "src" / "demo.py").write_text(
        "def demo():\n    return True\n",
        encoding="utf-8",
    )
    (project_root / "tests").mkdir()
    (project_root / "tests" / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(project_root)
    task = ProductTask(
        task_id="adapter-task",
        project_root=str(project_root.resolve()),
        kind="feature",
        title="Add demo feature",
        objective="Implement demo behavior in the Python source",
        requirements=("Update src demo", "Verify tests"),
        constraints=("Preserve architecture",),
        definition_of_done=("Feature works", "Tests pass"),
        status="ready_for_planning",
    )
    draft = generate_execution_plan(task=task, project=project)
    plan = approve_execution_plan(draft, current_task=task)
    return build_context_selection(task=task, project=project, plan=plan)


def test_context_selection_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    selection = _selection(project_root)
    adapter = ContextWorkspaceAdapter(tmp_path / "workspace")

    adapter.save_selection(selection)
    loaded = adapter.get_for_plan(selection.plan_id)

    assert loaded == selection
    assert adapter.path.is_file()


def test_context_selection_list_can_filter_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    selection = _selection(project_root)
    adapter = ContextWorkspaceAdapter(tmp_path / "workspace")
    adapter.save_selection(selection)

    assert adapter.list_selections(project_root=selection.project_root) == (selection,)
    assert adapter.list_selections(project_root="/other") == ()
