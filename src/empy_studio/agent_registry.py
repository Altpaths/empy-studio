from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .agent_contracts import AgentSpec, RuntimeTask


class AgentRegistry:
    def __init__(self, agents: list[AgentSpec] | None = None) -> None:
        self._agents: dict[str, AgentSpec] = {}
        for agent in agents or []:
            self.register(agent)

    def register(self, agent: AgentSpec) -> None:
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> AgentSpec:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {agent_id}") from exc

    def select(self, task: RuntimeTask) -> AgentSpec:
        if task.preferred_agent:
            preferred = self.get(task.preferred_agent)
            if not set(task.required_capabilities).issubset(preferred.capabilities):
                raise ValueError(
                    f"Preferred agent {preferred.agent_id} does not satisfy task capabilities"
                )
            return preferred

        required = set(task.required_capabilities)
        candidates = [
            agent
            for agent in self._agents.values()
            if required.issubset(set(agent.capabilities))
        ]
        if not candidates:
            raise ValueError(
                f"No agent can satisfy capabilities for task {task.task_id}: "
                f"{sorted(required)}"
            )

        candidates.sort(
            key=lambda agent: (
                len(set(agent.capabilities) - required),
                agent.agent_id,
            )
        )
        return candidates[0]

    def all(self) -> list[AgentSpec]:
        return [self._agents[key] for key in sorted(self._agents)]

    def describe(self) -> list[dict[str, Any]]:
        return [asdict(self._agents[key]) for key in sorted(self._agents)]
