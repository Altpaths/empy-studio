from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    apply_budget_usage,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
    policy_for_preset,
    start_budget_run,
)


def _prepared_inputs(root: Path):
    (root / "pyproject.toml").write_text(
        '[project]\nname="budget-demo"\n',
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
        task_id="budget-task",
        project_root=str(root.resolve()),
        kind="feature",
        title="Add bounded feature",
        objective="Implement a bounded feature and verify it",
        requirements=("Update Python source", "Run tests"),
        constraints=("Do not modify unrelated files",),
        definition_of_done=("Feature works", "Tests pass"),
        status="ready_for_planning",
    )
    draft = generate_execution_plan(task=task, project=project)
    approved = approve_execution_plan(draft, current_task=task)
    selection = build_context_selection(
        task=task,
        project=project,
        plan=approved,
    )
    return task, approved, selection


def test_budget_requires_approved_matching_plan(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    task, approved, selection = _prepared_inputs(root)
    project = DefaultProjectService().detect(root)
    draft = generate_execution_plan(task=task, project=project)

    with pytest.raises(ValueError, match="approved"):
        build_token_budget(plan=draft, selection=selection)

    other = replace(selection, plan_id="different")
    with pytest.raises(ValueError, match="do not match"):
        build_token_budget(plan=approved, selection=other)


def test_budget_is_visible_per_agent_before_execution(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)

    budget = build_token_budget(
        plan=plan,
        selection=selection,
        policy=policy_for_preset("economy"),
    )

    assert budget.status == "draft"
    assert budget.preset == "economy"
    assert len(budget.allocations) == len(plan.steps)
    assert budget.total_limit_tokens > budget.estimated_context_tokens
    assert all(item.max_retries == 1 for item in budget.allocations)
    assert all(item.max_handoffs == 1 for item in budget.allocations)
    assert all(item.total_limit_tokens > 0 for item in budget.allocations)


def test_locked_budget_is_required_before_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)
    draft_budget = build_token_budget(plan=plan, selection=selection)

    with pytest.raises(ValueError, match="locked"):
        start_budget_run(draft_budget)

    locked = lock_token_budget(draft_budget)
    state = start_budget_run(locked)

    assert locked.status == "locked"
    assert locked.locked_at is not None
    assert state.status == "ready"


def test_retry_limit_stops_repeated_loop(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)
    budget = lock_token_budget(
        build_token_budget(
            plan=plan,
            selection=selection,
            policy=policy_for_preset("economy"),
        )
    )
    state = start_budget_run(budget)
    allocation = budget.allocations[0]

    first = apply_budget_usage(
        budget=budget,
        state=state,
        kind="retry",
        step_id=allocation.step_id,
        requested_tokens=allocation.retry_tokens_per_attempt,
    )
    second = apply_budget_usage(
        budget=budget,
        state=first.state,
        kind="retry",
        step_id=allocation.step_id,
        requested_tokens=allocation.retry_tokens_per_attempt,
    )
    third = apply_budget_usage(
        budget=budget,
        state=second.state,
        kind="retry",
        step_id=allocation.step_id,
        requested_tokens=allocation.retry_tokens_per_attempt,
    )

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "retry limit reached"
    assert second.state.usage_for_step(allocation.step_id).stopped is True
    assert third.allowed is False
    assert third.state.total_tokens_used == first.state.total_tokens_used


def test_handoff_limit_is_finite(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)
    budget = lock_token_budget(
        build_token_budget(plan=plan, selection=selection)
    )
    state = start_budget_run(budget)
    allocation = budget.allocations[0]

    accepted = apply_budget_usage(
        budget=budget,
        state=state,
        kind="handoff",
        step_id=allocation.step_id,
        requested_tokens=allocation.handoff_tokens_per_event,
    )
    denied = apply_budget_usage(
        budget=budget,
        state=accepted.state,
        kind="handoff",
        step_id=allocation.step_id,
        requested_tokens=allocation.handoff_tokens_per_event,
    )

    assert accepted.allowed is True
    assert denied.allowed is False
    assert denied.reason == "handoff limit reached"


def test_total_or_planning_cap_auto_stops_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)
    budget = lock_token_budget(
        build_token_budget(plan=plan, selection=selection)
    )
    state = start_budget_run(budget)

    decision = apply_budget_usage(
        budget=budget,
        state=state,
        kind="planning",
        requested_tokens=budget.planning_limit_tokens + 1,
    )

    assert decision.allowed is False
    assert decision.state.status == "stopped"
    assert decision.reason == "planning token limit reached"


def test_hard_total_limit_rejects_oversized_budget(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, plan, selection = _prepared_inputs(root)
    policy = replace(
        policy_for_preset("economy"),
        hard_total_limit=100,
    )

    with pytest.raises(ValueError, match="hard_total_limit"):
        build_token_budget(
            plan=plan,
            selection=selection,
            policy=policy,
        )
