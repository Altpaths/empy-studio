from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TaskStatus = Literal["pending", "ready", "running", "passed", "failed", "blocked", "skipped"]


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    capabilities: tuple[str, ...]
    adapter: str
    max_attempts: int = 1
    timeout_seconds: float = 300.0
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSpec":
        return cls(
            agent_id=str(data["agent_id"]),
            name=str(data.get("name", data["agent_id"])),
            capabilities=tuple(str(item) for item in data.get("capabilities", [])),
            adapter=str(data.get("adapter", "local")),
            max_attempts=max(1, int(data.get("max_attempts", 1))),
            timeout_seconds=max(0.1, float(data.get("timeout_seconds", 300.0))),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class RuntimeTask:
    task_id: str
    title: str
    required_capabilities: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = ()
    preferred_agent: str | None = None
    failure_policy: Literal["stop", "continue", "block_dependents"] = "block_dependents"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeTask":
        return cls(
            task_id=str(data["task_id"]),
            title=str(data.get("title", data["task_id"])),
            required_capabilities=tuple(str(item) for item in data.get("required_capabilities", [])),
            depends_on=tuple(str(item) for item in data.get("depends_on", [])),
            context=dict(data.get("context", {})),
            acceptance_criteria=tuple(str(item) for item in data.get("acceptance_criteria", [])),
            preferred_agent=data.get("preferred_agent"),
            failure_policy=data.get("failure_policy", "block_dependents"),
        )


@dataclass
class AgentInput:
    run_id: str
    task: RuntimeTask
    agent: AgentSpec
    context: dict[str, Any]
    memory: dict[str, Any]
    handoffs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": asdict(self.task),
            "agent": asdict(self.agent),
            "context": self.context,
            "memory": self.memory,
            "handoffs": self.handoffs,
        }


@dataclass
class AgentOutput:
    status: Literal["passed", "failed"]
    result: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentOutput":
        status = str(data.get("status", "failed"))
        if status not in {"passed", "failed"}:
            raise ValueError("Agent output status must be 'passed' or 'failed'")
        return cls(
            status=status,
            result=dict(data.get("result", {})),
            evidence=list(data.get("evidence", [])),
            memory_updates=dict(data.get("memory_updates", {})),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
