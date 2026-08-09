from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    generate_execution_plan,
)


def laravel_project(
    root: Path,
):
    (root / "artisan").write_text(
        "#!/usr/bin/env php\n",
        encoding="utf-8",
    )
    (root / "composer.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (root / "resources").mkdir()
    (root / "tests").mkdir()
    return (
        DefaultProjectService()
        .detect(root)
    )


def php_project(
    root: Path,
):
    (root / "composer.json").write_text(
        '{"name":"demo/php-app"}\n',
        encoding="utf-8",
    )
    (root / "index.php").write_text(
        "<?php echo 'ok';\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "tests").mkdir()
    return DefaultProjectService().detect(root)


def task(
    root: Path,
) -> ProductTask:
    return ProductTask(
        task_id="task-1",
        project_root=str(root.resolve()),
        kind="ui_improvement",
        title="Improve homepage UI",
        objective=(
            "Improve the homepage without redesign"
        ),
        requirements=(
            "Keep Dana",
            "Use Vazir font",
            "Center hero content",
        ),
        constraints=(
            "Do not redesign the website",
        ),
        definition_of_done=(
            "Requested UI changes are visible",
            "Tests pass",
        ),
        status="ready_for_planning",
    )


def test_generates_bounded_plan(
    tmp_path: Path,
) -> None:
    value = generate_execution_plan(
        task=task(tmp_path),
        project=laravel_project(tmp_path),
    )

    assert value.status == "draft"
    assert value.risk == "low"
    assert "resources/views/" in (
        value.likely_paths
    )
    assert value.estimated_agents >= 2
    assert value.estimated_tokens > 0


def test_plan_has_valid_dependencies(
    tmp_path: Path,
) -> None:
    value = generate_execution_plan(
        task=task(tmp_path),
        project=laravel_project(tmp_path),
    )

    known = {
        step.step_id
        for step in value.steps
    }
    assert all(
        set(step.depends_on) <= known
        for step in value.steps
    )


def test_plain_php_plan_includes_application_and_test_scopes(
    tmp_path: Path,
) -> None:
    value = generate_execution_plan(
        task=task(tmp_path),
        project=php_project(tmp_path),
    )

    assert value.project_type == "php"
    assert "src/" in value.likely_paths
    assert "tests/" in value.likely_paths


def test_approval_freezes_plan(
    tmp_path: Path,
) -> None:
    current = task(tmp_path)
    value = generate_execution_plan(
        task=current,
        project=laravel_project(tmp_path),
    )

    approved = approve_execution_plan(
        value,
        current_task=current,
    )

    assert approved.status == "approved"
    assert approved.approved_at is not None

    with pytest.raises(
        ValueError,
        match="draft",
    ):
        approve_execution_plan(
            approved,
            current_task=current,
        )


def test_changed_task_cannot_approve(
    tmp_path: Path,
) -> None:
    current = task(tmp_path)
    value = generate_execution_plan(
        task=current,
        project=laravel_project(tmp_path),
    )

    changed = ProductTask(
        **{
            **current.__dict__,
            "requirements": (
                *current.requirements,
                "New requirement",
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="changed",
    ):
        approve_execution_plan(
            value,
            current_task=changed,
        )
