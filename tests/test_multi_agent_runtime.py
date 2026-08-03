from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from empy_studio.agent_adapters import CommandAdapter, LocalAdapter
from empy_studio.agent_contracts import AgentOutput, AgentSpec, RuntimeTask
from empy_studio.agent_registry import AgentRegistry
from empy_studio.execution_graph import execution_waves
from empy_studio.multi_agent_runtime import MultiAgentRuntime


def test_registry_selects_narrowest_capable_agent() -> None:
    registry = AgentRegistry([
        AgentSpec("general", "General", ("planning", "coding"), "local"),
        AgentSpec("planner", "Planner", ("planning",), "local"),
    ])
    task = RuntimeTask("t1", "Plan", ("planning",))
    assert registry.select(task).agent_id == "planner"


def test_execution_waves_are_dependency_aware() -> None:
    tasks = [
        RuntimeTask("plan", "Plan", ("planning",)),
        RuntimeTask("code", "Code", ("coding",), depends_on=("plan",)),
        RuntimeTask("docs", "Docs", ("docs",), depends_on=("plan",)),
        RuntimeTask("verify", "Verify", ("verify",), depends_on=("code", "docs")),
    ]
    assert execution_waves(tasks) == [["plan"], ["code", "docs"], ["verify"]]


def test_cycle_is_rejected() -> None:
    tasks = [
        RuntimeTask("a", "A", (), depends_on=("b",)),
        RuntimeTask("b", "B", (), depends_on=("a",)),
    ]
    with pytest.raises(ValueError, match="cycle"):
        execution_waves(tasks)


def test_runtime_passes_handoffs_and_updates_memory(tmp_path: Path) -> None:
    seen: list[dict] = []

    def handler(payload):
        seen.append(payload.to_dict())
        return AgentOutput(
            status="passed",
            result={"completed": payload.task.task_id},
            memory_updates={"last": payload.task.task_id},
        )

    agent = AgentSpec("worker", "Worker", ("plan", "build"), "local")
    runtime = MultiAgentRuntime(
        registry=AgentRegistry([agent]),
        adapters={"local": LocalAdapter(handler)},
        state_root=tmp_path / "runs",
        memory_root=tmp_path / "memory",
    )
    tasks = [
        RuntimeTask("plan", "Plan", ("plan",)),
        RuntimeTask("build", "Build", ("build",), depends_on=("plan",)),
    ]
    result = runtime.run(tasks, run_id="run-1")
    assert result["status"] == "passed"
    assert seen[1]["handoffs"]["plan"]["completed"] == "plan"
    memory = json.loads((tmp_path / "memory/worker.json").read_text(encoding="utf-8"))
    assert memory["revision"] == 2
    assert memory["data"]["last"] == "build"


def test_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def handler(payload):
        del payload
        attempts["count"] += 1
        if attempts["count"] == 1:
            return AgentOutput(status="failed", error="temporary")
        return AgentOutput(status="passed", result={"ok": True})

    agent = AgentSpec("worker", "Worker", ("build",), "local", max_attempts=2)
    runtime = MultiAgentRuntime(
        registry=AgentRegistry([agent]),
        adapters={"local": LocalAdapter(handler)},
        state_root=tmp_path / "runs",
        memory_root=tmp_path / "memory",
    )
    result = runtime.run([RuntimeTask("build", "Build", ("build",))], run_id="retry")
    assert result["status"] == "passed"
    assert len(result["tasks"]["build"]["attempts"]) == 2


def test_failed_dependency_blocks_dependent_task(tmp_path: Path) -> None:
    def handler(payload):
        if payload.task.task_id == "plan":
            return AgentOutput(status="failed", error="no plan")
        return AgentOutput(status="passed")

    agent = AgentSpec("worker", "Worker", ("plan", "build"), "local")
    runtime = MultiAgentRuntime(
        registry=AgentRegistry([agent]),
        adapters={"local": LocalAdapter(handler)},
        state_root=tmp_path / "runs",
        memory_root=tmp_path / "memory",
    )
    result = runtime.run([
        RuntimeTask("plan", "Plan", ("plan",)),
        RuntimeTask("build", "Build", ("build",), depends_on=("plan",)),
    ])
    assert result["tasks"]["plan"]["status"] == "failed"
    assert result["tasks"]["build"]["status"] == "blocked"


def test_command_adapter_enforces_timeout(tmp_path: Path) -> None:
    script = tmp_path / "sleep.py"
    script.write_text(
        "import time\ntime.sleep(2)\n",
        encoding="utf-8",
    )
    adapter = CommandAdapter([sys.executable, str(script), "{input}", "{output}"])
    agent = AgentSpec("slow", "Slow", (), "command", timeout_seconds=0.05)
    task = RuntimeTask("slow-task", "Slow task", ())
    from empy_studio.agent_contracts import AgentInput

    output = adapter.execute(
        AgentInput("run", task, agent, {}, {}, {}),
        timeout_seconds=0.05,
    )
    assert output.status == "failed"
    assert "timed out" in (output.error or "")
