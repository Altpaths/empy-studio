from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.desktop.agent_dispatcher_workspace_adapter import (
    AgentDispatcherWorkspaceAdapter,
)


def _graph(root: Path):
    (root / "pyproject.toml").write_text(
        '[project]\nname="dispatcher-store"\n',
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "feature.py").write_text(
        "def feature() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert True\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(root)
    task = ProductTask(
        task_id="stored-dispatch-task",
        project_root=str(root.resolve()),
        kind="feature",
        title="Add backend feature",
        objective="Implement backend feature and verify tests",
        requirements=("Update Python source", "Run tests"),
        constraints=("Keep scope bounded",),
        definition_of_done=("Tests pass",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(
        task=task,
        project=project,
        plan=plan,
    )
    budget = lock_token_budget(
        build_token_budget(plan=plan, selection=selection)
    )
    return build_agent_run_graph(
        plan=plan,
        selection=selection,
        budget=budget,
    )


def test_agent_run_graph_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    graph = _graph(root)
    store = AgentDispatcherWorkspaceAdapter(tmp_path / "workspace")

    store.save_graph(graph)
    loaded = store.get_for_budget(graph.budget_id)

    assert loaded == graph
    assert store.list_graphs(project_root=graph.project_root) == (graph,)


def test_latest_graph_replaces_same_graph_identity(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    graph = _graph(root)
    store = AgentDispatcherWorkspaceAdapter(tmp_path / "workspace")

    store.save_graph(graph)
    store.save_graph(graph)

    assert store.list_graphs() == (graph,)
