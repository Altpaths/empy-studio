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


def test_persian_php_homepage_ticket_gets_a_writer_for_nested_entrypoint(
    tmp_path: Path,
) -> None:
    public_html = tmp_path / "public_html"
    public_html.mkdir()
    (public_html / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (public_html / "index.php").write_text(
        "<?php echo 'home';\n",
        encoding="utf-8",
    )
    (public_html / "tests").mkdir()
    project = DefaultProjectService().detect(tmp_path)
    current = ProductTask(
        task_id="persian-homepage-ticket",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="صفحه ایندکس",
        objective="ارتباط دهی و همگام سازی لینک ها و دکمه ها را بررسی و اصلاح کن",
        requirements=("صفحه اول قابل استفاده باشد",),
        constraints=(),
        definition_of_done=("Verification واقعی موفق شود",),
        status="ready_for_planning",
    )

    value = generate_execution_plan(task=current, project=project)

    agents = {step.suggested_agent for step in value.steps}
    assert {"discovery", "frontend", "backend", "quality"} <= agents
    assert any(path.startswith("public_html/") for path in value.likely_paths)


def test_path_fragments_do_not_create_unrelated_frontend_agents(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"demo","scripts":{"test":"node tests/test_greeting.js"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "greeting.js").write_text(
        "module.exports = { greeting: () => 'Hello' };\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_greeting.js").write_text(
        "require('../src/greeting');\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(tmp_path)
    current = ProductTask(
        task_id="path-fragment-task",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="Change the greeting and update its test",
        objective=(
            "Change the greeting in src/greeting.js and update "
            "tests/test_greeting.js accordingly"
        ),
        requirements=("Run npm test",),
        constraints=("Do not change package.json",),
        definition_of_done=("The requested change is verified",),
        status="ready_for_planning",
    )

    value = generate_execution_plan(task=current, project=project)

    assert "implement-backend" in {step.step_id for step in value.steps}
    assert all(step.suggested_agent != "frontend" for step in value.steps)


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


def test_custom_actionable_ticket_gets_a_generic_writer(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "greeting.py").write_text(
        "def greeting():\n    return 'Hello'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    project = DefaultProjectService().detect(tmp_path)
    actionable = ProductTask(
        task_id="custom-write-task",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="Change greeting",
        objective="Change the greeting and update its test",
        requirements=("Change greeting", "Update the test", "Run tests"),
        constraints=("Do not change unrelated files",),
        definition_of_done=("Requested work is complete",),
        status="ready_for_planning",
    )

    plan = generate_execution_plan(task=actionable, project=project)

    assert "implement-backend" in {step.step_id for step in plan.steps}
