from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from empy_studio.core import (
    AgentDefinition,
    AgentRegistry,
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    default_agent_registry,
    generate_execution_plan,
    lock_token_budget,
)


def _prepared_inputs(
    root: Path,
    *,
    rich_task: bool = True,
):
    (root / "composer.json").write_text(
        '{"name":"demo/app"}\n',
        encoding="utf-8",
    )
    (root / "resources" / "views").mkdir(parents=True)
    (root / "resources" / "views" / "home.blade.php").write_text(
        "<main>Home</main>\n",
        encoding="utf-8",
    )
    (root / "app" / "Http" / "Controllers").mkdir(parents=True)
    (root / "app" / "Http" / "Controllers" / "HomeController.php").write_text(
        "<?php class HomeController {}\n",
        encoding="utf-8",
    )
    (root / "app" / "Http" / "Middleware").mkdir(parents=True)
    (root / "app" / "Http" / "Middleware" / "Authenticate.php").write_text(
        "<?php class Authenticate {}\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "release.yml").write_text(
        "name: release\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "FeatureTest.php").write_text(
        "<?php assert(true);\n",
        encoding="utf-8",
    )
    (root / ".env").write_text("SECRET=protected\n", encoding="utf-8")

    project = DefaultProjectService().detect(root)
    if rich_task:
        kind = "release"
        title = "Update UI backend authentication and release workflow"
        objective = (
            "Implement frontend layout, backend route, authentication security, "
            "tests, and release preparation"
        )
        requirements = (
            "Update the homepage UI",
            "Add backend controller behavior",
            "Review authentication permissions",
            "Prepare release workflow",
            "Run tests",
        )
    else:
        kind = "custom"
        title = "Inspect project documentation"
        objective = "Understand the current project and verify tests"
        requirements = ("Read project markers", "Run tests")

    task = ProductTask(
        task_id="dispatch-task",
        project_root=str(root.resolve()),
        kind=kind,
        title=title,
        objective=objective,
        requirements=requirements,
        constraints=("Do not modify unrelated files",),
        definition_of_done=("Requested scope is verified",),
        status="ready_for_planning",
    )
    draft = generate_execution_plan(task=task, project=project)
    plan = approve_execution_plan(draft, current_task=task)
    selection = build_context_selection(
        task=task,
        project=project,
        plan=plan,
    )
    budget = lock_token_budget(
        build_token_budget(plan=plan, selection=selection)
    )
    return plan, selection, budget


def test_dispatch_requires_locked_matching_inputs(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan, selection, locked = _prepared_inputs(root)
    draft_budget = replace(locked, status="draft", locked_at=None)

    with pytest.raises(ValueError, match="locked"):
        build_agent_run_graph(
            plan=plan,
            selection=selection,
            budget=draft_budget,
        )

    mismatched = replace(locked, selection_id="other")
    with pytest.raises(ValueError, match="do not match"):
        build_agent_run_graph(
            plan=plan,
            selection=selection,
            budget=mismatched,
        )


def test_only_relevant_planned_agents_are_selected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan, selection, budget = _prepared_inputs(root, rich_task=False)

    graph = build_agent_run_graph(
        plan=plan,
        selection=selection,
        budget=budget,
    )

    assert tuple(node.agent_role for node in graph.nodes) == (
        "discovery",
        "quality",
    )
    assert {node.agent_id for node in graph.nodes} == {
        "discovery-agent",
        "quality-agent",
    }
    assert len(graph.registry.agents) > len(graph.nodes)


def test_capability_matching_rejects_unsatisfied_role(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan, selection, budget = _prepared_inputs(root, rich_task=False)
    incomplete_registry = AgentRegistry(
        agents=(
            AgentDefinition(
                agent_id="discovery-agent",
                display_name="Discovery Agent",
                role="discovery",
                capabilities=(
                    "inspect-project",
                    "read-context",
                    "bounded-execution",
                ),
                ownership_patterns=(),
            ),
        )
    )

    with pytest.raises(ValueError, match="quality"):
        build_agent_run_graph(
            plan=plan,
            selection=selection,
            budget=budget,
            registry=incomplete_registry,
        )


def test_file_ownership_has_single_writer_and_protects_secrets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan, selection, budget = _prepared_inputs(root)

    graph = build_agent_run_graph(
        plan=plan,
        selection=selection,
        budget=budget,
    )

    paths = [item.relative_path for item in graph.ownership]
    assert len(paths) == len(set(paths))
    assert ".env" in graph.protected_exclusions
    assert ".env" not in paths
    assert all(
        len(
            [
                node
                for node in graph.nodes
                if item.relative_path in node.owned_files
            ]
        )
        <= 1
        for item in graph.ownership
    )
    assert all(
        not node.owned_files
        for node in graph.nodes
        if node.agent_role in {"discovery", "quality"}
    )


def test_dependency_waves_preserve_plan_sequence(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    plan, selection, budget = _prepared_inputs(root)

    graph = build_agent_run_graph(
        plan=plan,
        selection=selection,
        budget=budget,
    )
    wave_by_node = {
        node_id: index
        for index, wave in enumerate(graph.waves, start=1)
        for node_id in wave
    }

    assert len(graph.nodes) == len(plan.steps)
    assert {node.step_id for node in graph.nodes} == {
        step.step_id for step in plan.steps
    }
    assert all(
        wave_by_node[dependency] < node.wave
        for node in graph.nodes
        for dependency in node.depends_on
    )
    assert all(node.token_limit > 0 for node in graph.nodes)


def test_default_registry_is_deterministic() -> None:
    first = default_agent_registry()
    second = default_agent_registry()

    assert first == second
    assert {agent.role for agent in first.agents} == {
        "discovery",
        "frontend",
        "backend",
        "quality",
        "security",
        "release",
    }


def test_writing_plan_without_owned_files_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "print('demo')\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="ui-without-files",
        project_root=str(tmp_path.resolve()),
        kind="ui_improvement",
        title="Improve the homepage UI",
        objective="Improve the homepage layout",
        requirements=("Update the homepage",),
        constraints=("Do not change unrelated behavior",),
        definition_of_done=("The homepage is improved",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))

    with pytest.raises(ValueError, match="no writable files"):
        build_agent_run_graph(plan=plan, selection=selection, budget=budget)


def test_missing_php_homepage_gets_virtual_frontend_ownership(tmp_path: Path) -> None:
    public_html = tmp_path / "public_html"
    public_html.mkdir()
    (public_html / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (public_html / "index.php").write_text("<?php echo 'home';\n", encoding="utf-8")
    (public_html / "about").mkdir()
    (public_html / "about" / "index.html").write_text(
        "<main><h1>About</h1></main>\n",
        encoding="utf-8",
    )
    (public_html / "tests").mkdir()
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="missing-php-homepage",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="صفحه ایندکس",
        objective="لینک ها و دکمه ها را برای صفحه اول اصلاح کن",
        requirements=("صفحه اول قابل استفاده باشد",),
        constraints=(),
        definition_of_done=("Verification موفق شود",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))

    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)

    frontend = next(node for node in graph.nodes if node.agent_role == "frontend")
    assert "public_html/index.html" in frontend.owned_files
    assert "public_html/index.html" in {
        item.relative_path for item in graph.ownership if item.owner_node_id == frontend.node_id
    }


def test_explicit_test_update_is_owned_by_the_writer(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "greeting.py").write_text(
        "def greeting():\n    return 'Hello'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_greeting.py").write_text(
        "def test_greeting():\n    assert greeting() == 'Hello'\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="custom-test-update",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="Change the greeting and update its test",
        objective="Change the greeting and update its test",
        requirements=("Change greeting", "Update the test", "Run tests"),
        constraints=("Do not change unrelated files",),
        definition_of_done=("The greeting and its test agree",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)

    backend = next(node for node in graph.nodes if node.agent_role == "backend")
    assert {"src/greeting.py", "tests/test_greeting.py"}.issubset(
        backend.owned_files
    )
    assert all(
        "tests/test_greeting.py" not in node.owned_files
        for node in graph.nodes
        if node.agent_role == "quality"
    )
