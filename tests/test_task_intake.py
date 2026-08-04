from __future__ import annotations

import pytest

from empy_studio.core import (
    TASK_TEMPLATES,
    build_product_task,
    mark_ready_for_planning,
    split_multiline,
)


def test_templates_include_custom() -> None:
    keys = {
        template.key
        for template in TASK_TEMPLATES
    }
    assert "custom" in keys
    assert "ui_improvement" in keys


def test_multiline_input_is_cleaned() -> None:
    assert split_multiline(
        "- First\n• Second\n\nThird"
    ) == (
        "First",
        "Second",
        "Third",
    )


def test_builds_custom_task() -> None:
    task = build_product_task(
        task_id="task-1",
        project_root="/tmp/project",
        kind="custom",
        title="Homepage update",
        objective="Improve the homepage",
        requirements_text=(
            "Keep Dana\nUse Vazir"
        ),
        constraints_text=(
            "Do not redesign"
        ),
        definition_of_done_text=(
            "Tests pass"
        ),
    )

    assert task.requirements == (
        "Keep Dana",
        "Use Vazir",
    )
    assert task.status == "draft"


def test_template_supplies_defaults() -> None:
    task = build_product_task(
        task_id="task-1",
        project_root="/tmp/project",
        kind="ui_improvement",
        title="UI update",
        objective="Improve UI",
        requirements_text="Center hero",
        constraints_text="",
        definition_of_done_text="",
    )

    assert task.constraints
    assert task.definition_of_done


def test_task_requires_requirements() -> None:
    with pytest.raises(
        ValueError,
        match="requirements",
    ):
        build_product_task(
            task_id="task-1",
            project_root="/tmp/project",
            kind="custom",
            title="Task",
            objective="Objective",
            requirements_text="",
            constraints_text="",
            definition_of_done_text="Done",
        )


def test_marks_ready_for_planning() -> None:
    task = build_product_task(
        task_id="task-1",
        project_root="/tmp/project",
        kind="custom",
        title="Task",
        objective="Objective",
        requirements_text="Requirement",
        constraints_text="",
        definition_of_done_text="Done",
    )

    ready = mark_ready_for_planning(task)

    assert ready.status == (
        "ready_for_planning"
    )
