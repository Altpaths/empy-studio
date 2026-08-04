from __future__ import annotations

import os
from pathlib import Path

import pytest

from empy_studio.core import (
    ContextPolicy,
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    generate_execution_plan,
)


def _laravel_project(root: Path):
    (root / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
    (root / "composer.json").write_text('{"name":"demo/app"}\n', encoding="utf-8")
    (root / "resources" / "views").mkdir(parents=True)
    (root / "resources" / "css").mkdir(parents=True)
    (root / "app" / "Http" / "Controllers").mkdir(parents=True)
    (root / "tests" / "Feature").mkdir(parents=True)
    (root / "resources" / "views" / "home.blade.php").write_text(
        "<main>" + "homepage content " * 30 + "</main>\n",
        encoding="utf-8",
    )
    (root / "resources" / "css" / "app.css").write_text(
        ".hero { display: grid; }\n",
        encoding="utf-8",
    )
    (root / "app" / "Http" / "Controllers" / "HomeController.php").write_text(
        "<?php class HomeController {}\n",
        encoding="utf-8",
    )
    (root / "tests" / "Feature" / "HomeTest.php").write_text(
        "<?php function test_homepage() {}\n",
        encoding="utf-8",
    )
    (root / ".env").write_text("APP_KEY=secret\n", encoding="utf-8")
    (root / "private.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.js").write_text(
        "secret dependency content\n",
        encoding="utf-8",
    )
    return DefaultProjectService().detect(root)


def _task(root: Path) -> ProductTask:
    return ProductTask(
        task_id="task-context",
        project_root=str(root.resolve()),
        kind="ui_improvement",
        title="Improve homepage UI",
        objective="Improve the homepage layout and preserve existing behavior",
        requirements=(
            "Update homepage view",
            "Adjust hero CSS",
            "Verify homepage test",
        ),
        constraints=("Do not change unrelated backend modules",),
        definition_of_done=("Homepage is improved", "Tests pass"),
        status="ready_for_planning",
    )


def _approved_plan(root: Path):
    task = _task(root)
    project = _laravel_project(root)
    draft = generate_execution_plan(task=task, project=project)
    return task, project, approve_execution_plan(draft, current_task=task)


def test_requires_approved_plan(tmp_path: Path) -> None:
    task = _task(tmp_path)
    project = _laravel_project(tmp_path)
    draft = generate_execution_plan(task=task, project=project)

    with pytest.raises(ValueError, match="approved"):
        build_context_selection(task=task, project=project, plan=draft)


def test_builds_one_visible_bounded_pack_per_plan_step(tmp_path: Path) -> None:
    task, project, plan = _approved_plan(tmp_path)
    policy = ContextPolicy(
        max_files_per_pack=2,
        max_bytes_per_file=64,
        max_total_bytes_per_pack=96,
        max_candidate_file_bytes=1024,
        max_candidates=50,
    )

    selection = build_context_selection(
        task=task,
        project=project,
        plan=plan,
        policy=policy,
    )

    assert len(selection.packs) == len(plan.steps)
    assert all(len(pack.files) <= 2 for pack in selection.packs)
    assert all(pack.total_bytes <= 96 for pack in selection.packs)
    assert selection.selected_files == sum(len(pack.files) for pack in selection.packs)
    assert any(item.content for pack in selection.packs for item in pack.files)
    assert any(item.truncated for pack in selection.packs for item in pack.files)


def test_sensitive_files_and_dependency_directories_are_protected(tmp_path: Path) -> None:
    task, project, plan = _approved_plan(tmp_path)

    selection = build_context_selection(task=task, project=project, plan=plan)
    selected_paths = {
        item.relative_path
        for pack in selection.packs
        for item in pack.files
    }
    protected_paths = {
        item.relative_path
        for item in selection.exclusions
        if item.protected
    }

    assert ".env" not in selected_paths
    assert "private.pem" not in selected_paths
    assert not any(path.startswith("node_modules/") for path in selected_paths)
    assert ".env" in protected_paths
    assert "private.pem" in protected_paths
    assert any(item.relative_path == "node_modules/" for item in selection.exclusions)


def test_relevance_prefers_task_scope_and_quality_files(tmp_path: Path) -> None:
    task, project, plan = _approved_plan(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "unrelated.md").write_text(
        "completely unrelated documentation\n",
        encoding="utf-8",
    )

    selection = build_context_selection(task=task, project=project, plan=plan)
    frontend_packs = [pack for pack in selection.packs if pack.agent_role == "frontend"]
    quality_packs = [pack for pack in selection.packs if pack.agent_role == "quality"]

    assert frontend_packs
    assert any(
        item.relative_path.startswith("resources/")
        for item in frontend_packs[0].files
    )
    assert quality_packs
    assert any(
        item.relative_path.startswith("tests/")
        for item in quality_packs[0].files
    )


def test_symlink_is_never_followed(tmp_path: Path) -> None:
    task, project, plan = _approved_plan(tmp_path)
    outside = tmp_path.parent / "outside-context-secret.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "resources" / "views" / "outside.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    selection = build_context_selection(task=task, project=project, plan=plan)

    assert all(
        item.relative_path != "resources/views/outside.txt"
        for pack in selection.packs
        for item in pack.files
    )
    assert any(
        item.relative_path == "resources/views/outside.txt" and item.protected
        for item in selection.exclusions
    )
