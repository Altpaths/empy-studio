from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_adapters import AgentAdapter
from .agent_contracts import AgentInput, AgentOutput, RuntimeTask
from .agent_memory import AgentMemoryStore
from .agent_registry import AgentRegistry
from .agent_scheduler import AgentScheduler
from .execution_graph import execution_waves, validate_graph


@dataclass(frozen=True)
class _PreparedTask:
    task: RuntimeTask
    agent: Any
    adapter: AgentAdapter
    payload: AgentInput
    scheduling: Any | None


@dataclass(frozen=True)
class _TaskExecution:
    task_id: str
    output: AgentOutput
    attempts: tuple[dict[str, Any], ...]
    started_at: str
    finished_at: str


class MultiAgentRuntime:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        adapters: dict[str, AgentAdapter],
        state_root: str | Path,
        memory_root: str | Path,
        scheduler: AgentScheduler | None = None,
        max_workers: int = 4,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.registry = registry
        self.adapters = adapters
        self.state_root = Path(state_root)
        self.memory = AgentMemoryStore(memory_root)
        self.scheduler = scheduler
        self.max_workers = max_workers

    def _save(self, state: dict[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        path = self.state_root / f"{state['run_id']}.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _select_agent(
        self,
        task: RuntimeTask,
        active_assignments: dict[str, int] | None = None,
    ) -> tuple[Any, Any | None]:
        if self.scheduler is None:
            return self.registry.select(task), None
        scheduling = self.scheduler.select(
            task,
            self.registry.all(),
            active_assignments,
        )
        return self.registry.get(scheduling.agent_id), scheduling

    @staticmethod
    def _execute_prepared(prepared: _PreparedTask) -> _TaskExecution:
        started_at = datetime.now(timezone.utc).isoformat()
        attempts: list[dict[str, Any]] = []
        output: AgentOutput | None = None
        for attempt in range(1, prepared.agent.max_attempts + 1):
            attempt_started = time.monotonic()
            attempt_started_at = datetime.now(timezone.utc).isoformat()
            try:
                output = prepared.adapter.execute(
                    prepared.payload,
                    prepared.agent.timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 — adapter boundary preserves run state.
                output = AgentOutput(status="failed", error=f"Adapter error: {exc}")
            attempt_finished_at = datetime.now(timezone.utc).isoformat()
            elapsed = round(time.monotonic() - attempt_started, 6)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": output.status,
                    "started_at": attempt_started_at,
                    "finished_at": attempt_finished_at,
                    "elapsed_seconds": elapsed,
                    "error": output.error,
                    "evidence": output.evidence,
                }
            )
            if output.status == "passed":
                break

        assert output is not None
        return _TaskExecution(
            task_id=prepared.task.task_id,
            output=output,
            attempts=tuple(attempts),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

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
            "max_workers": self.max_workers,
            "schedule": [],
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
        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="empy-agent",
        ) as executor:
            for wave_index, wave in enumerate(waves):
                if stop_all:
                    break

                eligible: list[str] = []
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
                    else:
                        eligible.append(task_id)

                remaining = eligible
                while remaining and not stop_all:
                    prepared: list[_PreparedTask] = []
                    deferred: list[str] = []
                    active_assignments: dict[str, int] = {}

                    for index, task_id in enumerate(remaining):
                        task = task_map[task_id]
                        task_state = state["tasks"][task_id]
                        try:
                            agent, scheduling = self._select_agent(task, active_assignments)
                        except (KeyError, ValueError) as exc:
                            if self.scheduler is not None:
                                try:
                                    self._select_agent(task)
                                except (KeyError, ValueError):
                                    task_state["status"] = "failed"
                                    task_state["error"] = str(exc)
                                    self._save(state)
                                    if task.failure_policy == "stop":
                                        stop_all = True
                                    continue
                                deferred.append(task_id)
                                continue
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
                        prepared.append(
                            _PreparedTask(
                                task=task,
                                agent=agent,
                                adapter=adapter,
                                payload=AgentInput(
                                    run_id=actual_run_id,
                                    task=task,
                                    agent=agent,
                                    context={**(shared_context or {}), **task.context},
                                    memory=dict(memory_document.get("data", {})),
                                    handoffs=handoffs,
                                ),
                                scheduling=scheduling,
                            )
                        )
                        active_assignments[agent.agent_id] = active_assignments.get(agent.agent_id, 0) + 1
                        if len(prepared) >= self.max_workers:
                            deferred.extend(remaining[index + 1 :])
                            break

                    if not prepared:
                        remaining = deferred
                        continue

                    batch_ids = [item.task.task_id for item in prepared]
                    state["schedule"].append(
                        {
                            "wave": wave_index,
                            "batch": len(state["schedule"]) + 1,
                            "task_ids": batch_ids,
                            "mode": "parallel" if len(batch_ids) > 1 else "serial",
                            "capacity": len(batch_ids),
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    for item in prepared:
                        task_state = state["tasks"][item.task.task_id]
                        task_state["status"] = "running"
                        task_state["agent_id"] = item.agent.agent_id
                        if item.scheduling is not None:
                            task_state["scheduling"] = item.scheduling.to_dict()
                        task_state["wave"] = wave_index
                    self._save(state)

                    futures = {
                        item.task.task_id: executor.submit(self._execute_prepared, item)
                        for item in prepared
                    }
                    executions = [futures[item.task.task_id].result() for item in prepared]
                    state["schedule"][-1]["finished_at"] = datetime.now(timezone.utc).isoformat()

                    for execution in executions:
                        task_id = execution.task_id
                        task = task_map[task_id]
                        task_state = state["tasks"][task_id]
                        output = execution.output
                        task_state["status"] = output.status
                        task_state["started_at"] = execution.started_at
                        task_state["finished_at"] = execution.finished_at
                        task_state["attempts"] = list(execution.attempts)
                        task_state["result"] = output.result
                        task_state["error"] = output.error
                        task_state["evidence"] = output.evidence
                        if output.memory_updates:
                            memory = self.memory.update(
                                task_state["agent_id"],
                                output.memory_updates,
                                run_id=actual_run_id,
                                task_id=task_id,
                            )
                            task_state["memory_revision"] = memory["revision"]
                        self._save(state)
                        if output.status == "failed" and task.failure_policy == "stop":
                            stop_all = True

                    remaining = deferred

        if stop_all:
            for task_state in state["tasks"].values():
                if task_state["status"] == "pending":
                    task_state["status"] = "skipped"
                    task_state["skipped_reason"] = "Run stopped by failure policy."

        schedule = state["schedule"]
        state["schedule_summary"] = {
            "batches": len(schedule),
            "parallel_batches": sum(item["mode"] == "parallel" for item in schedule),
            "max_observed_parallelism": max(
                (item["capacity"] for item in schedule),
                default=0,
            ),
        }

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
