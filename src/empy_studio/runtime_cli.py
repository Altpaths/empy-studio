from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_adapters import AgentAdapter, CommandAdapter
from .agent_contracts import AgentSpec
from .agent_registry import AgentRegistry
from .common import load_json
from .multi_agent_runtime import MultiAgentRuntime, load_runtime_tasks


def run_manifest(manifest_path: str, output_root: str) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    agents = [AgentSpec.from_dict(item) for item in manifest.get("agents", [])]
    registry = AgentRegistry(agents)
    adapters: dict[str, AgentAdapter] = {}
    for adapter_id, config in manifest.get("adapters", {}).items():
        command = config.get("command", [])
        adapters[str(adapter_id)] = CommandAdapter([str(item) for item in command])

    root = Path(output_root)
    runtime = MultiAgentRuntime(
        registry=registry,
        adapters=adapters,
        state_root=root / "runs",
        memory_root=root / "memory",
    )
    return runtime.run(
        load_runtime_tasks(manifest),
        run_id=manifest.get("run_id"),
        shared_context=dict(manifest.get("shared_context", {})),
    )
