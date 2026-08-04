from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.core import ProjectDescriptor
from empy_studio.workspace import SQLiteWorkspaceStore


def test_workspace_starts_at_schema_version_one(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    assert store.schema_version() == 1


def test_projects_survive_store_restart(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"
    project_root = tmp_path / "project"
    project_root.mkdir()

    first = SQLiteWorkspaceStore(database)
    saved = first.save_project(
        ProjectDescriptor(
            root=project_root,
            project_type="python",
            display_name="Example",
        )
    )

    second = SQLiteWorkspaceStore(database)
    projects = second.list_projects()

    assert len(projects) == 1
    assert projects[0].project_id == saved.project_id
    assert projects[0].root == str(project_root.resolve())


def test_tasks_runs_and_settings_are_persistent(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = SQLiteWorkspaceStore(database)
    project = store.save_project(
        ProjectDescriptor(
            root=project_root,
            project_type="laravel",
            display_name="Kit4Kids",
        )
    )
    task = store.create_task(
        project_id=project.project_id,
        title="Homepage refinement",
        request_text="Keep Dana and improve the homepage.",
        task_kind="custom",
        contract={"constraints": ["Do not redesign"]},
    )
    run = store.create_run(
        task_id=task.task_id,
        project_id=project.project_id,
        summary="Run planned",
    )
    store.update_run(
        run.run_id,
        state="completed",
        summary="Run completed",
        driver_name="codex",
        evidence_path="runs/evidence.json",
    )
    store.set_setting("appearance", {"theme": "system"})

    reopened = SQLiteWorkspaceStore(database)

    assert reopened.get_task(task.task_id).contract == {
        "constraints": ["Do not redesign"]
    }
    assert reopened.get_run(run.run_id).state == "completed"
    assert reopened.get_setting("appearance") == {"theme": "system"}


def test_removing_project_cascades_tasks_and_runs(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.save_project(
        ProjectDescriptor(root=root, project_type="python", display_name="P")
    )
    task = store.create_task(
        project_id=project.project_id,
        title="Task",
        request_text="Do work",
        task_kind="custom",
        contract={},
    )
    run = store.create_run(
        task_id=task.task_id,
        project_id=project.project_id,
        summary="Planned",
    )

    store.remove_project(project.project_id)

    with pytest.raises(KeyError):
        store.get_task(task.task_id)
    with pytest.raises(KeyError):
        store.get_run(run.run_id)


def test_future_schema_is_rejected(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "workspace.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', '999')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer"):
        SQLiteWorkspaceStore(database)
