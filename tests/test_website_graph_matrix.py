from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.core.path_policy import (
    is_agent_denied_relative_path,
    is_root_scope,
)
from empy_studio.core.planner import classify_intent

_DESIGN_INPUTS: tuple[tuple[str, set[str]], ...] = (
    ("Add contact form", {"frontend"}),
    ("Add contact form with email delivery", {"frontend", "backend"}),
    ("Add data table", {"frontend"}),
    ("Create database table", {"backend"}),
    ("Add realtime chart from API", {"frontend", "backend"}),
    ("Add login", {"frontend", "backend", "security"}),
    ("Add payment checkout", {"frontend", "backend", "security"}),
    ("Improve accessibility/WCAG", {"frontend"}),
    ("Generate dynamic sitemap route", {"frontend", "backend"}),
    ("Upload images to storage", {"frontend", "backend"}),
    ("Add search", {"frontend"}),
    ("Add search with database results", {"frontend", "backend"}),
    ("Add filters and pagination", {"frontend"}),
    ("Add email notifications", {"frontend", "backend"}),
    ("Add user roles", {"frontend", "backend", "security"}),
    ("Add admin panel", {"frontend", "backend"}),
    ("Add subscription billing", {"frontend", "backend"}),
    ("Add websocket chat", {"frontend", "backend"}),
    ("Add captcha", {"frontend", "backend", "security"}),
    ("Add rate limiting", {"backend", "security"}),
    ("Add audit log", {"backend", "security"}),
    ("Add dark mode", {"frontend"}),
    ("Add service worker", {"frontend"}),
    ("Add PWA offline support", {"frontend"}),
    ("Add export CSV", {"frontend", "backend"}),
    ("Add PDF report", {"frontend", "backend"}),
    ("Add file download", {"frontend", "backend"}),
    ("Add multilingual support", {"frontend"}),
    ("Fix broken links", {"frontend"}),
    ("Create users table", {"backend"}),
    ("ورود و ثبت‌نام را اضافه کن", {"frontend", "backend", "security"}),
)

_WRITING_ROLES = {"frontend", "backend", "coordinator", "release"}


def _create_fixture(root: Path, framework: str) -> None:
    if framework == "php":
        app = root / "public_html"
        app.mkdir()
        (app / "composer.json").write_text("{}\n", encoding="utf-8")
        (app / "index.php").write_text("<?php echo 'home';\n", encoding="utf-8")
        (app / "FinanceService.php").write_text(
            "<?php class FinanceService {}\n",
            encoding="utf-8",
        )
        (app / "assets").mkdir()
        (app / "assets" / "app.js").write_text("console.log('ready');\n", encoding="utf-8")
        (app / "assets" / "app.css").write_text("body { margin: 0; }\n", encoding="utf-8")
        (app / "database").mkdir()
        (app / "database" / "schema.sql").write_text(
            "CREATE TABLE example (id INT);\n",
            encoding="utf-8",
        )
        (app / "services").mkdir()
        (app / "services" / "MailService.php").write_text("<?php\n", encoding="utf-8")
        return
    if framework == "html":
        (root / "index.html").write_text(
            "<html><head></head><body><main>home</main></body></html>\n",
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets" / "app.js").write_text("console.log('ready');\n", encoding="utf-8")
        (root / "assets" / "app.css").write_text("body { margin: 0; }\n", encoding="utf-8")
        return
    if framework == "node":
        (root / "package.json").write_text(
            '{"name":"matrix-site","scripts":{"test":"node --check server.js"}}\n',
            encoding="utf-8",
        )
        (root / "src").mkdir()
        (root / "src" / "App.tsx").write_text(
            "export default function App() { return <main />; }\n",
            encoding="utf-8",
        )
        (root / "src" / "main.tsx").write_text(
            "import App from './App';\n",
            encoding="utf-8",
        )
        (root / "server.js").write_text("require('http');\n", encoding="utf-8")
        return
    if framework == "laravel":
        (root / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
        (root / "composer.json").write_text("{}\n", encoding="utf-8")
        for directory in (
            "resources/views",
            "resources/css",
            "resources/js",
            "routes",
            "app/Http",
            "app/Models",
            "database",
        ):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "resources/views/welcome.blade.php").write_text(
            "<main>home</main>\n",
            encoding="utf-8",
        )
        (root / "routes/web.php").write_text("<?php\n", encoding="utf-8")
        (root / "app/Http/Controller.php").write_text("<?php\n", encoding="utf-8")
        (root / "database/schema.sql").write_text(
            "CREATE TABLE example (id INT);\n",
            encoding="utf-8",
        )
        return
    raise AssertionError(f"unknown fixture: {framework}")


@pytest.mark.parametrize("framework", ("php", "html", "node", "laravel"))
@pytest.mark.parametrize("prompt, expected_domains", _DESIGN_INPUTS)
def test_website_input_graph_matrix_is_bounded_and_complete(
    tmp_path: Path,
    framework: str,
    prompt: str,
    expected_domains: set[str],
) -> None:
    _create_fixture(tmp_path, framework)
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id=f"matrix-{framework}",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title=prompt,
        objective=prompt,
        requirements=(prompt,),
        constraints=("Do not change unrelated files",),
        definition_of_done=("The requested behavior is verified",),
        status="ready_for_planning",
    )

    profile = classify_intent(prompt)
    assert set(profile.domains) == expected_domains
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)
    graph.validate()

    assert budget.status == "locked"
    assert len({item.relative_path for item in graph.ownership}) == len(graph.ownership)
    for node in graph.nodes:
        if node.agent_role in _WRITING_ROLES:
            assert node.owned_files, f"{framework}/{prompt} lost its writer scope"
        if node.agent_role == "security":
            # Security is an audit/review specialist. Remediation is owned by
            # backend/frontend nodes, so the audit node cannot widen scope.
            assert node.owned_files == ()
        for path in (*node.owned_files, *node.read_only_files):
            assert not is_root_scope(path)
            assert not is_agent_denied_relative_path(path)
    for item in graph.ownership:
        assert not is_root_scope(item.relative_path)
        assert not is_agent_denied_relative_path(item.relative_path)


def test_node_server_entrypoint_is_backend_owned(tmp_path: Path) -> None:
    _create_fixture(tmp_path, "node")
    project = DefaultProjectService().detect(tmp_path)
    task = ProductTask(
        task_id="node-server-ownership",
        project_root=str(tmp_path.resolve()),
        kind="custom",
        title="Add contact form with email delivery",
        objective="Add contact form with email delivery",
        requirements=("Add contact form with email delivery",),
        constraints=(),
        definition_of_done=("The server accepts the form",),
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
    assert backend.owned_files == ("server.js",)
