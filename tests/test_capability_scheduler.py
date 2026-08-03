from __future__ import annotations

import pytest

from empy_studio.agent_contracts import AgentSpec, RuntimeTask
from empy_studio.agent_scheduler import AgentScheduleProfile, AgentScheduler
from empy_studio.capability_graph import Capability, CapabilityGraph


def graph() -> CapabilityGraph:
    return CapabilityGraph([
        Capability("engineering"),
        Capability("python", aliases=("py",), implies=("engineering",), weight=2.0),
        Capability("testing", requires=("engineering",), weight=1.5),
    ])


def test_alias_and_implication_are_expanded() -> None:
    assert graph().expand(["py"]) == {"python", "engineering"}


def test_unknown_reference_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown capability"):
        CapabilityGraph([Capability("python", implies=("engineering",))])


def test_scheduler_prefers_narrow_reliable_agent() -> None:
    agents = [
        AgentSpec("general", "General", ("python", "testing"), "local"),
        AgentSpec("specialist", "Specialist", ("python",), "local"),
    ]
    profiles = [
        AgentScheduleProfile("general", cost=2.0, reliability=0.95),
        AgentScheduleProfile("specialist", priority=1, cost=1.0, reliability=0.99),
    ]
    scheduler = AgentScheduler(graph(), profiles)
    decision = scheduler.select(RuntimeTask("task", "Task", ("py",)), agents)
    assert decision.agent_id == "specialist"
    assert "engineering" in decision.required_capabilities


def test_capacity_excludes_busy_agent() -> None:
    agents = [
        AgentSpec("a", "A", ("python",), "local"),
        AgentSpec("b", "B", ("python",), "local"),
    ]
    profiles = [
        AgentScheduleProfile("a", capacity=1, priority=10),
        AgentScheduleProfile("b", capacity=1),
    ]
    scheduler = AgentScheduler(graph(), profiles)
    decision = scheduler.select(
        RuntimeTask("task", "Task", ("python",)),
        agents,
        active_assignments={"a": 1},
    )
    assert decision.agent_id == "b"


def test_unsatisfied_task_is_rejected() -> None:
    scheduler = AgentScheduler(graph())
    with pytest.raises(ValueError, match="No schedulable agent"):
        scheduler.select(
            RuntimeTask("task", "Task", ("testing",)),
            [AgentSpec("python", "Python", ("python",), "local")],
        )
