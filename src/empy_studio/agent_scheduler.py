from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .agent_contracts import AgentSpec, RuntimeTask
from .capability_graph import CapabilityGraph


@dataclass(frozen=True)
class AgentScheduleProfile:
    agent_id: str
    capacity: int = 1
    priority: int = 0
    cost: float = 1.0
    reliability: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentScheduleProfile":
        return cls(
            agent_id=str(data["agent_id"]),
            capacity=max(1, int(data.get("capacity", 1))),
            priority=int(data.get("priority", 0)),
            cost=max(0.0, float(data.get("cost", 1.0))),
            reliability=min(1.0, max(0.0, float(data.get("reliability", 1.0)))),
        )


@dataclass(frozen=True)
class SchedulingDecision:
    task_id: str
    agent_id: str
    score: float
    required_capabilities: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentScheduler:
    def __init__(
        self,
        graph: CapabilityGraph,
        profiles: list[AgentScheduleProfile] | None = None,
    ) -> None:
        self.graph = graph
        self.profiles = {profile.agent_id: profile for profile in profiles or []}

    def _profile(self, agent: AgentSpec) -> AgentScheduleProfile:
        return self.profiles.get(agent.agent_id, AgentScheduleProfile(agent.agent_id))

    def rank(
        self,
        task: RuntimeTask,
        agents: list[AgentSpec],
        active_assignments: dict[str, int] | None = None,
    ) -> list[SchedulingDecision]:
        active = active_assignments or {}
        required = self.graph.expand(list(task.required_capabilities))
        decisions: list[SchedulingDecision] = []

        for agent in agents:
            profile = self._profile(agent)
            load = active.get(agent.agent_id, 0)
            if load >= profile.capacity:
                continue

            available = self.graph.expand(list(agent.capabilities))
            if not required.issubset(available):
                continue

            matched_weight = sum(self.graph.weight(item) for item in required)
            extra_weight = sum(
                self.graph.weight(item)
                for item in available - required
            )
            load_ratio = load / profile.capacity
            score = (
                matched_weight * 100
                + profile.priority * 10
                + profile.reliability * 10
                - extra_weight
                - profile.cost
                - load_ratio * 20
            )
            reasons = (
                f"satisfies {len(required)} required capabilities",
                f"capacity {profile.capacity - load}/{profile.capacity} available",
                f"reliability {profile.reliability:.2f}",
                f"cost {profile.cost:.2f}",
            )
            decisions.append(
                SchedulingDecision(
                    task_id=task.task_id,
                    agent_id=agent.agent_id,
                    score=round(score, 4),
                    required_capabilities=tuple(sorted(required)),
                    matched_capabilities=tuple(sorted(required & available)),
                    reasons=reasons,
                )
            )

        decisions.sort(key=lambda item: (-item.score, item.agent_id))
        return decisions

    def select(
        self,
        task: RuntimeTask,
        agents: list[AgentSpec],
        active_assignments: dict[str, int] | None = None,
    ) -> SchedulingDecision:
        ranked = self.rank(task, agents, active_assignments)
        if not ranked:
            raise ValueError(
                f"No schedulable agent satisfies task {task.task_id}: "
                f"{sorted(task.required_capabilities)}"
            )
        return ranked[0]
