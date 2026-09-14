from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    policy_for_preset,
)


def _budget(tmp_path: Path, *, specialists: bool):
    tmp_path.mkdir()
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"node test.js"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "public").mkdir()
    project = DefaultProjectService().detect(tmp_path)
    instruction = (
        "Use separate specialist agents for frontend, backend and release."
        if specialists
        else "Keep the work bounded and economical."
    )
    task = ProductTask(
        task_id="token-efficiency",
        project_root=str(tmp_path.resolve()),
        kind="release",
        title="Update frontend backend release",
        objective=(
            "Update the frontend, backend integration and release files together. "
            + instruction
        ),
        requirements=("Keep tests passing",),
        constraints=(),
        definition_of_done=("Changes are verified",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    return plan, build_token_budget(
        plan=plan,
        selection=selection,
        policy=policy_for_preset("economy"),
    )


def test_adaptive_coordinator_reduces_planned_provider_calls(tmp_path: Path) -> None:
    economy_plan, economy = _budget(tmp_path / "economy", specialists=False)
    specialist_plan, specialist = _budget(tmp_path / "specialist", specialists=True)

    assert [step.suggested_agent for step in economy_plan.steps] == ["coordinator"]
    assert len(specialist_plan.steps) == 3
    assert economy.total_limit_tokens < specialist.total_limit_tokens
