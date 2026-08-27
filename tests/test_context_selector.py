from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from empy_studio.core import (
    ContextPolicy,
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    context_selector,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.core.planner import PlanStep
from empy_studio.core.project_brain import build_project_brain_index


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
    (root / "config").mkdir()
    (root / "config" / "config.php").write_text(
        "<?php return ['password' => 'secret'];\n",
        encoding="utf-8",
    )
    (root / "config" / "config.example.php").write_text(
        "<?php return ['password' => ''];\n",
        encoding="utf-8",
    )
    (root / "storage" / "logs").mkdir(parents=True)
    (root / "storage" / "logs" / "app.log").write_text(
        "sensitive runtime log\n",
        encoding="utf-8",
    )
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
    assert "config/config.php" in protected_paths
    assert "storage/logs/app.log" in protected_paths
    assert "config/config.php" not in selected_paths
    assert "storage/logs/app.log" not in selected_paths
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
    assert quality_packs == []


def test_scoped_code_ticket_skips_discovery_and_repeated_documentation(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"scoped-demo","scripts":{"test":"node tests/test_greeting.js"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Project documentation that is not part of this code change.\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "greeting.js").write_text(
        "export const greeting = () => 'Hello';\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_greeting.js").write_text(
        "// greeting test\n",
        encoding="utf-8",
    )

    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="scoped-code-ticket",
        project_root=str(tmp_path.resolve()),
        kind="feature",
        title="Change src/greeting.js and tests/test_greeting.js",
        objective="Update the greeting implementation and its test.",
        requirements=(
            "Change src/greeting.js",
            "Update tests/test_greeting.js",
            "Run the project tests",
        ),
        constraints=("Do not change README.md or package.json",),
        definition_of_done=("The greeting and test agree",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )

    assert "discovery" not in {step.step_id for step in plan.steps}
    assert "quality" not in {step.step_id for step in plan.steps}
    selection = build_context_selection(task=task, project=project, plan=plan)
    named = {"src/greeting.js", "tests/test_greeting.js"}
    for pack in selection.packs:
        if pack.agent_role in {"backend", "quality"}:
            assert "README.md" not in {item.relative_path for item in pack.files}
            assert {item.relative_path for item in pack.files} <= named


def test_frontend_writer_pack_excludes_sql_and_uses_head_tail_excerpt(
    tmp_path: Path,
) -> None:
    public_html = tmp_path / "public_html"
    (public_html / "database").mkdir(parents=True)
    (public_html / "assets").mkdir()
    (public_html / "index.html").write_text(
        "<head>important-head</head>\n"
        + ("<section>middle</section>\n" * 900)
        + "<footer>important-tail</footer>\n",
        encoding="utf-8",
    )
    (public_html / "assets" / "home.css").write_text(
        ".hero { display: grid; }\n",
        encoding="utf-8",
    )
    (public_html / "database" / "migration.sql").write_text(
        "create table unrelated(id int);\n",
        encoding="utf-8",
    )
    (public_html / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php -l index.php"}}\n',
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(tmp_path)
    current = ProductTask(
        task_id="bounded-persian-homepage",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="برای سایت صفحه اول درست کن و لینگ بده",
        objective="برای سایت صفحه اول درست کن و لینگ بده",
        requirements=("صفحه اصلی کامل باشد",),
        constraints=(),
        definition_of_done=("بررسی محلی موفق شود",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=current, project=project),
        current_task=current,
    )

    selection = build_context_selection(task=current, project=project, plan=plan)
    frontend = next(pack for pack in selection.packs if pack.agent_role == "frontend")
    paths = {item.relative_path for item in frontend.files}
    index = next(item for item in frontend.files if item.relative_path == "public_html/index.html")

    assert frontend.total_bytes <= 8_192
    assert len(frontend.files) <= 3
    assert frontend.files[0].relative_path == "public_html/index.html"
    assert not any(path.endswith(".sql") for path in paths)
    assert "important-head" in index.content
    assert "important-tail" in index.content
    assert "Empy omitted the bounded middle section" in index.content

    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)
    frontend_node = next(node for node in graph.nodes if node.agent_role == "frontend")
    assert frontend_node.owned_files == ("public_html/index.html",)


def test_documentation_ticket_keeps_named_readme_in_writer_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"docs-demo"}\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("Old note\n", encoding="utf-8")
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="readme-ticket",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="Update README.md",
        objective="Add a short follow-up note to README.md.",
        requirements=("Change README.md only",),
        constraints=(),
        definition_of_done=("The note is present",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    backend = next(pack for pack in selection.packs if pack.agent_role == "backend")
    assert "README.md" in {item.relative_path for item in backend.files}


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


def test_optional_project_brain_boosts_indexed_symbol_relevance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "brain-demo"\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text(
        "class PaymentGateway:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "zeta.py").write_text(
        "class Unrelated:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alpha.py").write_text(
        "def test_gateway():\n    assert True\n",
        encoding="utf-8",
    )
    task = ProductTask(
        task_id="task-brain-context",
        project_root=str(tmp_path.resolve()),
        kind="feature",
        title="Wire PaymentGateway",
        objective="Use the PaymentGateway integration point",
        requirements=("Update the implementation",),
        constraints=(),
        definition_of_done=("Tests pass",),
        status="ready_for_planning",
    )
    project = DefaultProjectService().detect(tmp_path)
    approved = approve_execution_plan(
        generate_execution_plan(task=task, project=project), current_task=task
    )
    plan = replace(
        approved,
        likely_paths=("src/",),
        steps=(
            PlanStep(
                step_id="step-backend",
                title="Update integration",
                objective="Wire PaymentGateway",
                depends_on=(),
                suggested_agent="backend",
                estimated_files=1,
                risk="low",
            ),
        ),
    )
    brain = build_project_brain_index(tmp_path).index
    monkeypatch.setattr(
        context_selector.os,
        "walk",
        lambda *_args, **_kwargs: pytest.fail("context selection should use the Project Brain index"),
    )
    policy = ContextPolicy(
        max_files_per_pack=1,
        max_bytes_per_file=512,
        max_total_bytes_per_pack=512,
        max_candidate_file_bytes=2048,
        max_candidates=20,
    )

    selection = build_context_selection(
        task=task,
        project=project,
        plan=plan,
        policy=policy,
        brain_index=brain,
    )

    backend_pack = next(pack for pack in selection.packs if pack.agent_role == "backend")
    assert backend_pack.files[0].relative_path == "src/alpha.py"
    assert "indexed imports or symbols match task" in backend_pack.files[0].reasons
