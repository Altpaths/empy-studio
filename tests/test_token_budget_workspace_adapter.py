from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.desktop.token_budget_workspace_adapter import (
    TokenBudgetWorkspaceAdapter,
)


def _budget(project_root: Path):
    (project_root / "pyproject.toml").write_text(
        '[project]\nname="budget-adapter"\n',
        encoding="utf-8",
    )
    (project_root / "src").mkdir()
    (project_root / "src" / "demo.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (project_root / "tests").mkdir()
    (project_root / "tests" / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(project_root)
    task = ProductTask(
        task_id="budget-adapter-task",
        project_root=str(project_root.resolve()),
        kind="feature",
        title="Persist budget",
        objective="Persist bounded token limits",
        requirements=("Use source context", "Keep retries finite"),
        constraints=("No execution",),
        definition_of_done=("Budget round trips",),
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
    return lock_token_budget(
        build_token_budget(plan=plan, selection=selection)
    )


def test_token_budget_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    budget = _budget(project_root)
    adapter = TokenBudgetWorkspaceAdapter(tmp_path / "workspace")

    adapter.save_budget(budget)
    loaded = adapter.get_for_selection(budget.selection_id)

    assert loaded == budget
    assert adapter.path.is_file()


def test_budget_list_can_filter_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    budget = _budget(project_root)
    adapter = TokenBudgetWorkspaceAdapter(tmp_path / "workspace")
    adapter.save_budget(budget)

    assert adapter.list_budgets(project_root=budget.project_root) == (budget,)
    assert adapter.list_budgets(project_root="/other") == ()
