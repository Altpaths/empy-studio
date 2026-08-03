from __future__ import annotations

from typing import Any

from .agent_contracts import AgentSpec, RuntimeTask
from .agent_scheduler import AgentScheduleProfile, AgentScheduler
from .capability_graph import Capability, CapabilityGraph
from .common import load_json


def build_schedule(manifest_path: str) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    graph = CapabilityGraph([
        Capability.from_dict(item)
        for item in manifest.get("capabilities", [])
    ])
    agents = [AgentSpec.from_dict(item) for item in manifest.get("agents", [])]
    profiles = [
        AgentScheduleProfile.from_dict(item)
        for item in manifest.get("profiles", [])
    ]
    tasks = [RuntimeTask.from_dict(item) for item in manifest.get("tasks", [])]
    scheduler = AgentScheduler(graph, profiles)
    active = {
        str(key): int(value)
        for key, value in manifest.get("active_assignments", {}).items()
    }

    decisions = []
    for task in tasks:
        decisions.append(scheduler.select(task, agents, active).to_dict())
    return {
        "engine": "capability_scheduler",
        "status": "planned",
        "capabilities": graph.describe(),
        "decisions": decisions,
    }
