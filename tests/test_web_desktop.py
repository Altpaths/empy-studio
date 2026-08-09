from __future__ import annotations

from pathlib import Path

from empy_studio.web_desktop import GuidedState


def test_guided_state_persists_project_and_follow_up_ticket(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    (source / "src").mkdir()
    (source / "src" / "service.py").write_text(
        "def run():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (source / "tests").mkdir()
    (source / "tests" / "test_service.py").write_text(
        "def test_run():\n    assert True\n",
        encoding="utf-8",
    )

    first = GuidedState(tmp_path / "empy-workspace")
    first.import_path(str(source))
    first.create_plan("Update the backend service\nRun the service tests")

    assert first.active_project_id is not None
    assert first.active_task_id is not None
    first_task_id = first.active_task_id
    assert first.phase == "plan"
    assert first.plan is not None
    assert any(node.owned_files for node in first.graph.nodes if node.agent_role == "backend")

    reopened = GuidedState(tmp_path / "empy-workspace")
    projects = reopened.public()["projects"]
    assert len(projects) == 1
    assert projects[0]["id"] == first.active_project_id
    assert len(projects[0]["tasks"]) == 1
    assert reopened.active_project_id == first.active_project_id
    assert reopened.active_task_id == first_task_id
    assert reopened.task is not None
    assert reopened.plan is not None
    assert reopened.phase == "plan"

    reopened.create_plan("Add a bounded follow-up to the backend service")
    assert len(reopened.public()["active_project"]["tasks"]) == 2
    reopened.select_task(first_task_id)
    assert reopened.active_task_id == first_task_id
    assert reopened.task is not None
    assert reopened.task.title == "Update the backend service"


def test_reset_keeps_project_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    project_id = state.active_project_id

    state.reset()

    assert state.active_project_id is None
    assert project_id is not None
    assert state.public()["projects"][0]["id"] == project_id
