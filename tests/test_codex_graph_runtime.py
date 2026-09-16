from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from empy_studio.core import (
    DefaultProjectService,
    DriverExecutionRequest,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.drivers import (
    CodexGraphRuntime,
    CodexInstallation,
    CodexNodeExecution,
    build_codex_node_prompt,
)
from empy_studio.token_usage import TokenUsage


def prepared(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname="runtime-demo"\n', encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "feature.py").write_text("def feature():\n    return True\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert True\n",
        encoding="utf-8",
    )
    detection = DefaultProjectService().detect(root)
    task = ProductTask(
        task_id="runtime-task",
        project_root=str(root.resolve()),
        kind="feature",
        title="Update feature and verify it",
        objective="Implement the backend feature and run tests",
        requirements=("Update Python source", "Run tests"),
        constraints=("Do not modify unrelated files",),
        definition_of_done=("Feature works", "Tests pass"),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=detection),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=detection, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)
    return detection, selection, budget, graph


class FakeDriver:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.requests: list[DriverExecutionRequest] = []
        self.cancelled = False

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        del refresh
        return CodexInstallation(
            availability="available",
            executable="/usr/local/bin/codex",
            version="codex-cli 1.2.3",
            authenticated=True,
            message="ready",
        )

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress=None,
    ) -> CodexNodeExecution:
        del on_progress
        self.requests.append(request)
        path = Path(artifact_dir)
        status = "failed" if self.fail_first and len(self.requests) == 1 else "completed"
        result = CodexNodeExecution(
            node_id=node_id,
            task_id=request.task_id,
            status=status,
            started_at="2026-08-04T00:00:00+00:00",
            finished_at="2026-08-04T00:00:01+00:00",
            return_code=1 if status == "failed" else 0,
            thread_id="thread-test",
            summary="failed" if status == "failed" else "completed",
            changed_files=(),
            event_count=0,
            events_path=str(path / "events.jsonl"),
            stderr_path=str(path / "stderr.log"),
            final_message_path=str(path / "final-message.md"),
            command_path=str(path / "command.json"),
            error_code="process_failed" if status == "failed" else None,
            error_message="provider failure" if status == "failed" else None,
            usage=(
                TokenUsage(
                    input=10 * len(self.requests),
                    output=3,
                    cached=2,
                    total=10 * len(self.requests) + 3,
                    source="provider",
                    provider="codex",
                )
                if status == "completed"
                else None
            ),
        )
        result.validate()
        return result

    def cancel(self) -> None:
        self.cancelled = True


def test_prompt_contains_bounded_context_and_safety_rules(tmp_path: Path) -> None:
    _, selection, _, graph = prepared(tmp_path)
    node = graph.nodes[0]

    prompt = build_codex_node_prompt(graph=graph, selection=selection, node=node)

    assert node.node_id in prompt
    assert "Do not commit, push, merge, tag, publish" in prompt
    assert "Bounded context pack" in prompt
    assert "Verification handoff" in prompt
    assert "Provider-neutral local estimate" in prompt
    assert "Writing nodes must not spend provider time" in prompt
    assert "Empy's verification pipeline" in prompt
    assert "No provider Quality node is planned" in prompt
    assert "EMPY_NODE_RESULT: PASS" in prompt
    assert "Do not claim that a provider Quality node" in prompt
    assert "current working tree and current file contents" in prompt
    assert "at most 4096 output characters" in prompt
    assert "line counts are unsafe" in prompt
    assert str(node.token_limit) in prompt

    compact_node = replace(
        node,
        owned_files=(node.owned_files[0],),
        read_only_files=(node.owned_files[1],),
    )
    compact_prompt = build_codex_node_prompt(
        graph=graph,
        selection=selection,
        node=compact_node,
        dependency_results=(
            CodexNodeExecution(
                node_id="upstream",
                task_id="runtime-task:upstream",
                status="completed",
                started_at="2026-08-04T00:00:00+00:00",
                finished_at="2026-08-04T00:00:01+00:00",
                return_code=0,
                thread_id=None,
                summary="upstream completed",
                changed_files=(),
                event_count=0,
                events_path=str(tmp_path / "events.jsonl"),
                stderr_path=str(tmp_path / "stderr.log"),
                final_message_path=str(tmp_path / "final.md"),
                command_path=str(tmp_path / "command.json"),
            ),
        ),
        compact_read_only_context=True,
    )
    read_only_file = next(
        item for item in selection.packs[0].files if item.relative_path == compact_node.read_only_files[0]
    )
    assert read_only_file.content not in compact_prompt
    assert read_only_file.sha256 in compact_prompt

    without_quality_nodes = tuple(
        item for item in graph.nodes if item.agent_role != "quality"
    )
    without_quality_ids = {item.node_id for item in without_quality_nodes}
    without_quality = replace(
        graph,
        nodes=without_quality_nodes,
        waves=tuple(
            tuple(node_id for node_id in wave if node_id in without_quality_ids)
            for wave in graph.waves
            if any(node_id in without_quality_ids for node_id in wave)
        ),
    )
    deterministic_prompt = build_codex_node_prompt(
        graph=without_quality,
        selection=selection,
        node=without_quality.nodes[0],
    )
    assert "Empy's deterministic verification pipeline" in deterministic_prompt


def test_prompt_contains_approved_user_task_contract(tmp_path: Path) -> None:
    _, selection, _, graph = prepared(tmp_path)
    node = graph.nodes[0]
    task = ProductTask(
        task_id=graph.task_id,
        project_root=graph.project_root,
        kind="feature",
        title="Add a greeting helper",
        objective="Add a shout helper without changing greet.",
        requirements=("Create shout(name) in the backend service.", "Keep greet unchanged."),
        constraints=("Do not modify tests.",),
        definition_of_done=("The helper is importable.", "Relevant tests pass."),
        status="ready_for_planning",
    )

    prompt = build_codex_node_prompt(
        graph=graph,
        selection=selection,
        node=node,
        task=task,
    )

    assert "Approved user task" in prompt
    assert task.objective in prompt
    assert task.requirements[0] in prompt
    assert task.constraints[0] in prompt
    assert task.definition_of_done[0] in prompt


def test_runtime_executes_dependency_order(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    driver = FakeDriver()
    runtime = CodexGraphRuntime(
        driver=driver,
        run_root=tmp_path / "runs",
        timeout_seconds=120,
    )

    result = runtime.run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "completed"
    assert tuple(item.node_id for item in result.node_results) == tuple(
        node_id for wave in graph.waves for node_id in wave
    )
    assert len(driver.requests) == len(graph.nodes)
    assert all(request.timeout_seconds == 120 for request in driver.requests)
    assert all(request.fresh_token_limit is not None for request in driver.requests)
    assert all(request.fresh_token_limit > 24_000 for request in driver.requests)
    for node, request in zip(graph.nodes, driver.requests, strict=True):
        assert request.handoff_after_first_file_change is False
        assert request.fresh_token_limit == node.token_limit
    accounting = result.to_dict()["budget_accounting"]
    assert accounting["cap_adjustment_tokens"] == 0
    assert accounting["usage_complete"] is True
    assert accounting["reported_cached_tokens"] == 2 * len(graph.nodes)
    assert result.usage is not None
    assert result.usage.input == sum(10 * index for index in range(1, len(graph.nodes) + 1))
    assert result.usage.output == 3 * len(graph.nodes)
    assert result.usage.cached == 2 * len(graph.nodes)
    assert result.usage.source == "provider"
    assert result.usage.provider == "codex"


def test_runtime_runs_independent_wave_in_parallel_when_driver_allows_it(
    tmp_path: Path,
) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    nodes = tuple(
        replace(node, depends_on=(), wave=1)
        for node in graph.nodes
    )
    independent_graph = replace(
        graph,
        nodes=nodes,
        waves=(tuple(node.node_id for node in nodes),),
    )
    independent_graph.validate()
    driver = FakeDriver()
    driver.supports_parallel_nodes = True
    runtime = CodexGraphRuntime(
        driver=driver,
        run_root=tmp_path / "runs",
        max_parallel_nodes=3,
    )

    result = runtime.run(
        graph=independent_graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "completed"
    assert len(result.schedule) == 1
    assert result.schedule[0].mode == "serial"
    assert result.schedule[0].capacity == 1
    assert tuple(item.node_id for item in result.node_results) == tuple(
        node.node_id for node in nodes
    )


def test_runtime_honors_cancel_before_worker_enters_run(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    driver = FakeDriver()
    runtime = CodexGraphRuntime(driver=driver, run_root=tmp_path / "runs")
    runtime.cancel()

    result = runtime.run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "cancelled"
    assert result.error_code == "cancelled"
    assert driver.requests == []


def test_failed_node_stops_and_skips_remaining_nodes(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    driver = FakeDriver(fail_first=True)
    runtime = CodexGraphRuntime(driver=driver, run_root=tmp_path / "runs")

    result = runtime.run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "failed"
    assert result.node_results[0].status == "failed"
    assert all(item.status == "skipped" for item in result.node_results[1:])
    assert len(driver.requests) == 1


def test_runtime_rejects_unlocked_budget(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    unlocked = replace(budget, status="draft", locked_at=None)
    runtime = CodexGraphRuntime(driver=FakeDriver(), run_root=tmp_path / "runs")

    try:
        runtime.run(
            graph=graph,
            selection=selection,
            budget=unlocked,
            project=detection.descriptor,
        )
    except ValueError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("unlocked budget should be rejected")



def test_runtime_rejects_dirty_git_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    driver = FakeDriver()
    runtime = CodexGraphRuntime(driver=driver, run_root=tmp_path / "runs")
    snapshot = SimpleNamespace(
        head="abc123",
        status={"src/feature.py": " M"},
    )
    monkeypatch.setattr(runtime, "_git_snapshot", lambda root: snapshot)

    result = runtime.run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "failed"
    assert result.error_code == "dirty_worktree"
    assert len(driver.requests) == 0


def test_git_snapshot_uses_relative_paths(tmp_path: Path) -> None:
    detection, _, _, _ = prepared(tmp_path)
    root = detection.descriptor.root
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "tests@example.com"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "Empy Tests"), cwd=root, check=True)
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "baseline"), cwd=root, check=True)
    (root / "src" / "feature.py").write_text("def feature():\n    return False\n", encoding="utf-8")

    snapshot = CodexGraphRuntime._git_snapshot(root)

    assert snapshot is not None
    assert snapshot.status == {"src/feature.py": " M"}


def test_absolute_provider_paths_are_normalized_to_project_relative(tmp_path: Path) -> None:
    root = (tmp_path / "project").resolve()
    root.mkdir()

    assert CodexGraphRuntime._normalize_changed_path(str(root / "src" / "feature.py"), root) == (
        "src/feature.py"
    )
    assert CodexGraphRuntime._normalize_changed_path("./src/feature.py", root) == "src/feature.py"
    assert CodexGraphRuntime._normalize_changed_path("/outside/file.py", root) == "/outside/file.py"


def test_runtime_fails_node_that_changes_unowned_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    driver = FakeDriver()
    runtime = CodexGraphRuntime(driver=driver, run_root=tmp_path / "runs")
    snapshots = iter(
        (
            None,
            None,
            None,
        )
    )
    monkeypatch.setattr(runtime, "_git_snapshot", lambda root: next(snapshots))
    monkeypatch.setattr(
        runtime,
        "_snapshot_delta",
        lambda before, after: {"unowned.txt"},
    )

    result = runtime.run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "failed"
    assert result.node_results[0].status == "failed"
    assert result.node_results[0].error_code == "scope_violation"
    assert "unowned.txt" in (result.node_results[0].error_message or "")
    assert len(driver.requests) == 1


def test_runtime_allows_exact_new_market_endpoint_but_not_unplanned_migration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    public_html = root / "public_html"
    (public_html / "assets").mkdir(parents=True)
    (public_html / "src").mkdir()
    (public_html / "database").mkdir()
    (public_html / "composer.json").write_text(
        '{"name":"holda/demo"}\n', encoding="utf-8"
    )
    (public_html / "assets.php").write_text("<?php echo 'assets';\n", encoding="utf-8")
    (public_html / "assets" / "app.js").write_text(
        "document.querySelector('[data-assets]');\n", encoding="utf-8"
    )
    (public_html / "src" / "FinanceService.php").write_text(
        "<?php class FinanceService {}\n", encoding="utf-8"
    )
    detection = DefaultProjectService().detect(root)
    text = "برای بخش دارایی ها یک نمودار با قیمت های واقعی لحظه ای اضافه کن"
    task = ProductTask(
        task_id="runtime-market-endpoint",
        project_root=str(root.resolve()),
        kind="custom",
        title=text,
        objective=text,
        requirements=("اطلاعات و قیمت ها واقعی جمع اوری شود",),
        constraints=("Do not change unrelated files",),
        definition_of_done=("The chart verification passes",),
        status="ready_for_planning",
    )
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=detection),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=detection, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)

    class EndpointDriver(FakeDriver):
        def __init__(self, *, add_migration: bool) -> None:
            super().__init__()
            self.add_migration = add_migration

        def execute_streaming(self, request, *, node_id, artifact_dir, on_progress=None):
            if request.task_id.endswith(":implement-frontend"):
                (root / "public_html" / "assets" / "app.js").write_text(
                    "document.body.dataset.marketChart = 'ready';\n", encoding="utf-8"
                )
            if request.task_id.endswith(":implement-backend"):
                (root / "public_html" / "asset-prices.php").write_text(
                    "<?php echo json_encode([]);\n", encoding="utf-8"
                )
                if self.add_migration:
                    (root / "public_html" / "database" / "migrate-asset-prices.sql").write_text(
                        "CREATE TABLE asset_prices (id INT);\n", encoding="utf-8"
                    )
            result = super().execute_streaming(
                request,
                node_id=node_id,
                artifact_dir=artifact_dir,
                on_progress=on_progress,
            )
            if request.task_id.endswith(":implement-frontend"):
                changed = ["public_html/assets/app.js"]
            elif request.task_id.endswith(":implement-backend"):
                changed = ["public_html/asset-prices.php"]
            else:
                changed = []
            if self.add_migration and request.task_id.endswith(":implement-backend"):
                changed.append("public_html/database/migrate-asset-prices.sql")
            return replace(result, changed_files=tuple(changed))

    allowed = CodexGraphRuntime(
        driver=EndpointDriver(add_migration=False),
        run_root=tmp_path / "allowed-run",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
        task=task,
    )
    assert allowed.status == "completed"
    assert "public_html/asset-prices.php" in {
        path for result in allowed.node_results for path in result.changed_files
    }

    blocked = CodexGraphRuntime(
        driver=EndpointDriver(add_migration=True),
        run_root=tmp_path / "blocked-run",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
        task=task,
    )
    assert blocked.status == "failed"
    assert blocked.error_code == "scope_violation"
    assert "migrate-asset-prices.sql" in (blocked.error_message or "")


def test_failed_usage_is_unknown_not_zero(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    result = CodexGraphRuntime(driver=FakeDriver(fail_first=True), run_root=tmp_path / "runs").run(
        graph=graph, selection=selection, budget=budget, project=detection.descriptor,
    )
    accounting = result.to_dict()["budget_accounting"]
    assert accounting["usage_complete"] is False
    assert accounting["unknown_usage_node_ids"] == [graph.nodes[0].node_id]
    assert accounting["nodes"][0]["reported_fresh_tokens"] is None


def test_small_locked_cap_is_preserved(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    graph = replace(graph, nodes=tuple(replace(node, token_limit=100) for node in graph.nodes))
    driver = FakeDriver()
    result = CodexGraphRuntime(driver=driver, run_root=tmp_path / "runs").run(
        graph=graph, selection=selection, budget=budget, project=detection.descriptor,
    )
    assert all(request.fresh_token_limit == 100 for request in driver.requests)
    assert result.to_dict()["budget_accounting"]["cap_adjustment_tokens"] == 0


def test_graph_cannot_raise_locked_allocation(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    graph = replace(graph, nodes=tuple(
        replace(node, token_limit=node.token_limit + 1) for node in graph.nodes
    ))
    with pytest.raises(ValueError, match="locked step token allocation"):
        CodexGraphRuntime(driver=FakeDriver(), run_root=tmp_path / "runs").run(
            graph=graph, selection=selection, budget=budget, project=detection.descriptor,
        )


def test_prompt_guard_stops_before_provider_and_records_serialized_size(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    constrained = replace(
        graph,
        nodes=tuple(replace(node, token_limit=1) for node in graph.nodes),
    )
    driver = FakeDriver()
    result = CodexGraphRuntime(
        driver=driver,
        run_root=tmp_path / "runs",
    ).run(
        graph=constrained,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "failed"
    assert result.error_code == "budget_exceeded"
    assert result.node_results[0].error_code == "budget_exceeded"
    assert driver.requests == []
    assert result.prompt_estimates
    node_id, prompt_tokens = result.prompt_estimates[0]
    assert node_id == constrained.nodes[0].node_id
    assert prompt_tokens > constrained.nodes[0].token_limit
    accounting = result.to_dict()["budget_accounting"]
    assert accounting["prompt_estimates"] == [
        {"node_id": node_id, "prompt_tokens": prompt_tokens}
    ]


def test_parallelization_rejects_ancestor_and_descendant_scopes(tmp_path: Path) -> None:
    _, _, _, graph = prepared(tmp_path)
    runtime = CodexGraphRuntime(driver=FakeDriver(), run_root=tmp_path / "runs")
    first = graph.nodes[0]
    second = replace(first, node_id=f"{first.node_id}-second")
    runtime.driver.supports_parallel_nodes = True  # type: ignore[attr-defined]

    assert not runtime._can_parallelize(
        (
            replace(first, owned_files=("src/",)),
            replace(second, owned_files=("src/components/Button.tsx",)),
        )
    )
    assert runtime._can_parallelize(
        (
            replace(first, owned_files=("src/",)),
            replace(second, owned_files=("public/",)),
        )
    )


def test_directory_creation_scope_never_authorizes_existing_file_edits(tmp_path: Path) -> None:
    detection, _, _, _ = prepared(tmp_path)
    existing = detection.descriptor.root / "src" / "existing.ts"
    existing.write_text("current\n", encoding="utf-8")
    runtime = CodexGraphRuntime(driver=FakeDriver(), run_root=tmp_path / "runs")

    existing_paths = runtime._existing_creation_paths(
        detection.descriptor.root,
        ("src/",),
    )
    assert "src/existing.ts" in existing_paths
    assert runtime._path_is_owned(
        "src/new.ts",
        ("src/",),
        root=detection.descriptor.root,
    )
    assert runtime._path_is_owned(
        "src/existing.ts",
        ("src/",),
        root=detection.descriptor.root,
    )
    assert not runtime._path_is_exactly_owned("src/existing.ts", ("src/",))


def test_provider_reported_symlink_change_fails_scope_audit(tmp_path: Path) -> None:
    detection, selection, budget, graph = prepared(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.py").write_text("print('escape')\n", encoding="utf-8")
    (detection.descriptor.root / "src" / "link.py").symlink_to(
        outside / "escape.py"
    )

    class SymlinkReportDriver(FakeDriver):
        def execute_streaming(self, request, *, node_id, artifact_dir, on_progress=None):
            result = super().execute_streaming(
                request,
                node_id=node_id,
                artifact_dir=artifact_dir,
                on_progress=on_progress,
            )
            return replace(result, changed_files=("src/link.py",))

    driver = SymlinkReportDriver()
    result = CodexGraphRuntime(
        driver=driver,
        run_root=tmp_path / "runs",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
    )

    assert result.status == "failed"
    assert result.error_code == "scope_violation"
    assert "src/link.py" in (result.error_message or "")
