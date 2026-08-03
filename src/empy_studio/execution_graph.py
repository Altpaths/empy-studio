from __future__ import annotations

from .agent_contracts import RuntimeTask


def validate_graph(tasks: list[RuntimeTask]) -> None:
    ids = [task.task_id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Task IDs must be unique")
    known = set(ids)
    for task in tasks:
        unknown = set(task.depends_on) - known
        if unknown:
            raise ValueError(
                f"Task {task.task_id} depends on unknown tasks: {sorted(unknown)}"
            )
        if task.task_id in task.depends_on:
            raise ValueError(f"Task {task.task_id} cannot depend on itself")

    pending = {task.task_id: set(task.depends_on) for task in tasks}
    while pending:
        ready = sorted(task_id for task_id, deps in pending.items() if not deps)
        if not ready:
            raise ValueError("Execution graph contains a cycle")
        for task_id in ready:
            pending.pop(task_id)
        for deps in pending.values():
            deps.difference_update(ready)


def execution_waves(tasks: list[RuntimeTask]) -> list[list[str]]:
    validate_graph(tasks)
    pending = {task.task_id: set(task.depends_on) for task in tasks}
    waves: list[list[str]] = []
    completed: set[str] = set()
    while pending:
        ready = sorted(
            task_id
            for task_id, deps in pending.items()
            if deps.issubset(completed)
        )
        if not ready:
            raise ValueError("Execution graph cannot make progress")
        waves.append(ready)
        completed.update(ready)
        for task_id in ready:
            pending.pop(task_id)
    return waves
