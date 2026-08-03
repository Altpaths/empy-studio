from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_adapters import AgentAdapter
from .agent_contracts import AgentInput, AgentOutput, RuntimeTask
from .agent_memory import AgentMemoryStore
from .agent_registry import AgentRegistry
from .agent_scheduler import AgentScheduler
from .execution_graph import execution_waves, validate_graph


class MultiAgentRuntime:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        adapters: dict[str, AgentAdapter],
        state_root: str | Path,
        memory_root: str | Path,
        scheduler: AgentScheduler | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = adapters
        self.state_root = Path(state_root)
        self.memory = AgentMemoryStore(memory_root)
        self.scheduler = scheduler

    def _save(self, state: dict[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        path = self.state_root / f"{state['run_id']}.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(
        self,
        tasks: list[RuntimeTask],
        *,
        run_id: str | None = None,
        shared_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_graph(tasks)
        actual_run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        waves = execution_waves(tasks)
        task_map = {task.task_id: task for task in tasks}
        state: dict[str, Any] = {
            "run_id": actual_run_id,
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "waves": waves,
            "tasks": {
                task.task_id: {
                    "status": "pending",
                    "title": task.title,
                    "depends_on": list(task.depends_on),
                    "attempts": [],
                }
                for task in tasks
            },
        }
        self._save(state)

        stop_all = False
        for wave_index, wave in enumerate(waves):
            if stop_all:
                break
            for task_id in wave:
                task = task_map[task_id]
                task_state = state["tasks"][task_id]
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if state["tasks"][dependency]["status"] != "passed"
                ]
                if failed_dependencies:
                    task_state["status"] = "blocked"
                    task_state["blocked_by"] = failed_dependencies
                    self._save(state)
                    continue

                try:
                    if self.scheduler is None:
                        agent = self.registry.select(task)
                        scheduling = None
                    else:
                        scheduling = self.scheduler.select(task, self.registry.all())
                        agent = self.registry.get(scheduling.agent_id)
                except (KeyError, ValueError) as exc:
                    task_state["status"] = "failed"
                    task_state["error"] = str(exc)
                    self._save(state)
                    if task.failure_policy == "stop":
                        stop_all = True
                    continue

                adapter = self.adapters.get(agent.adapter)
                if adapter is None:
                    task_state["status"] = "failed"
                    task_state["error"] = f"No adapter registered: {agent.adapter}"
                    self._save(state)
                    if task.failure_policy == "stop":
                        stop_all = True
                    continue

                handoffs = {
                    dependency: state["tasks"][dependency].get("result", {})
                    for dependency in task.depends_on
                }
                memory_document = self.memory.load(agent.agent_id)
                payload = AgentInput(
                    run_id=actual_run_id,
                    task=task,
                    agent=agent,
                    context={**(shared_context or {}), **task.context},
                    memory=dict(memory_document.get("data", {})),
                    handoffs=handoffs,
                )

                task_state["status"] = "running"
                task_state["agent_id"] = agent.agent_id
                if scheduling is not None:
                    task_state["scheduling"] = scheduling.to_dict()
                task_state["wave"] = wave_index
                self._save(state)

                output: AgentOutput | None = None
                for attempt in range(1, agent.max_attempts + 1):
                    started = time.monotonic()
                    try:
                        output = adapter.execute(payload, agent.timeout_seconds)
                    except Exception as exc:  # noqa: BLE001 — adapter boundary preserves run state.
                        output = AgentOutput(status="failed", error=f"Adapter error: {exc}")
                    elapsed = round(time.monotonic() - started, 6)
                    task_state["attempts"].append({
                        "attempt": attempt,
                        "status": output.status,
                        "elapsed_seconds": elapsed,
                        "error": output.error,
                        "evidence": output.evidence,
                    })
                    self._save(state)
                    if output.status == "passed":
                        break

                assert output is not None
                task_state["status"] = output.status
                task_state["result"] = output.result
                task_state["error"] = output.error
                task_state["evidence"] = output.evidence
                if output.memory_updates:
                    memory = self.memory.update(
                        agent.agent_id,
                        output.memory_updates,
                        run_id=actual_run_id,
                        task_id=task_id,
                    )
                    task_state["memory_revision"] = memory["revision"]
                self._save(state)

                if output.status == "failed" and task.failure_policy == "stop":
                    stop_all = True

        statuses = [item["status"] for item in state["tasks"].values()]
        state["status"] = "passed" if statuses and all(status == "passed" for status in statuses) else "failed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["summary"] = {
            status: statuses.count(status)
            for status in sorted(set(statuses))
        }
        self._save(state)
        return state


def load_runtime_tasks(data: dict[str, Any]) -> list[RuntimeTask]:
    raw_tasks = data.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise TypeError("'tasks' must be a list")
    return [RuntimeTask.from_dict(item) for item in raw_tasks]
