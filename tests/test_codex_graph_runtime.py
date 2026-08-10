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
    assert str(node.token_limit) in prompt


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
    assert result.schedule[0].mode == "parallel"
    assert result.schedule[0].capacity == 3
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
