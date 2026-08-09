from __future__ import annotations

from pathlib import Path

from empy_studio.benchmark import (
    build_load_save_project_brain_index,
    run_local_benchmark,
)
from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)


def _prepared(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='bench'\n", encoding="utf-8")
    (root / "README.md").write_text("Benchmark demo\n" * 80, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")
    (root / "src" / "large.py").write_text("VALUE = 'context saving demo'\n" * 300, encoding="utf-8")
    (root / ".env").write_text("SECRET=never-index\n", encoding="utf-8")
    detection = DefaultProjectService().detect(root)
    task = ProductTask(
        task_id="bench-task",
        project_root=str(root.resolve()),
        kind="feature",
        title="Update app",
        objective="Update app and tests",
        requirements=("Update Python source",),
        constraints=("Do not modify secrets",),
        definition_of_done=("Relevant tests pass",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(generate_execution_plan(task=task, project=detection), current_task=task)
    selection = build_context_selection(task=task, project=detection, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    index = build_load_save_project_brain_index(
        project_id="project-1",
        project=detection,
        path=tmp_path / "brain" / "project-1.json",
    )
    return detection, task, plan, selection, budget, index


def test_project_brain_index_is_local_safe_and_reloadable(tmp_path: Path) -> None:
    detection, _task, _plan, _selection, _budget, first = _prepared(tmp_path)

    second = build_load_save_project_brain_index(
        project_id="project-1",
        project=detection,
        path=tmp_path / "brain" / "project-1.json",
    )

    assert second.records == first.records
    assert second.stats()["reused_files"] == len(second.records)
    assert "src/app.py" in [item.relative_path for item in second.files]
    assert ".env" not in [item.relative_path for item in second.files]
    assert second.stats()["file_count"] == len(second.records)


def test_benchmark_math_uses_same_task_and_bounded_selection(tmp_path: Path) -> None:
    detection, task, plan, selection, budget, index = _prepared(tmp_path)

    result = run_local_benchmark(
        task=task,
        project=detection,
        plan=plan,
        brain_index=index,
        selection=selection,
        budget=budget,
    )

    assert result.candidate_files
    assert set(result.selected_files).issubset(set(result.candidate_files))
    assert result.full_context_estimate_tokens >= result.bounded_context_estimate_tokens
    assert result.saved_tokens == (
        result.full_context_estimate_tokens - result.bounded_context_estimate_tokens
    )
    assert result.savings_percentage >= 0
    assert result.source_estimate == "provider_neutral_local_estimate"
