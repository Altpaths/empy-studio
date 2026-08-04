from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.core import (
    AgentCapability,
    AgentDefinition,
    AgentRegistry,
    AgentRunGraph,
    AgentRunNode,
    FileOwnership,
    GraphStatus,
)
from empy_studio.core.planner import AgentRole


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _capability_tuple(value: object) -> tuple[AgentCapability, ...]:
    return cast(tuple[AgentCapability, ...], _string_tuple(value))


class AgentDispatcherWorkspaceAdapter:
    """Persist pre-execution Agent Run Graphs."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace_root / "agent-run-graphs.json"

    def save_graph(self, graph: AgentRunGraph) -> None:
        graph.validate()
        existing = {
            str(item["graph_id"]): item
            for item in self._read()
            if "graph_id" in item
        }
        existing[graph.graph_id] = graph.to_dict()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                list(existing.values()),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get_for_budget(self, budget_id: str) -> AgentRunGraph | None:
        matches = [
            item
            for item in self._read()
            if item.get("budget_id") == budget_id
        ]
        if not matches:
            return None
        return self._from_dict(matches[-1])

    def list_graphs(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[AgentRunGraph, ...]:
        values = self._read()
        if project_root is not None:
            values = [
                item
                for item in values
                if item.get("project_root") == project_root
            ]
        return tuple(self._from_dict(item) for item in values)

    def _from_dict(self, value: dict[str, object]) -> AgentRunGraph:
        raw_registry = value.get("registry")
        raw_nodes = value.get("nodes", [])
        raw_ownership = value.get("ownership", [])
        raw_waves = value.get("waves", [])
        if not isinstance(raw_registry, dict):
            raise TypeError("registry must be an object")
        if not isinstance(raw_nodes, list):
            raise TypeError("nodes must be a list")
        if not isinstance(raw_ownership, list):
            raise TypeError("ownership must be a list")
        if not isinstance(raw_waves, list):
            raise TypeError("waves must be a list")

        raw_agents = raw_registry.get("agents", [])
        if not isinstance(raw_agents, list):
            raise TypeError("registry agents must be a list")
        agents: list[AgentDefinition] = []
        for raw in raw_agents:
            if not isinstance(raw, dict):
                continue
            agents.append(
                AgentDefinition(
                    agent_id=str(raw["agent_id"]),
                    display_name=str(raw["display_name"]),
                    role=cast(AgentRole, str(raw["role"])),
                    capabilities=_capability_tuple(raw.get("capabilities")),
                    ownership_patterns=_string_tuple(
                        raw.get("ownership_patterns")
                    ),
                    priority=_as_int(raw["priority"], "priority"),
                    enabled=bool(raw["enabled"]),
                )
            )

        nodes: list[AgentRunNode] = []
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            nodes.append(
                AgentRunNode(
                    node_id=str(raw["node_id"]),
                    step_id=str(raw["step_id"]),
                    title=str(raw["title"]),
                    objective=str(raw["objective"]),
                    agent_id=str(raw["agent_id"]),
                    agent_role=cast(AgentRole, str(raw["agent_role"])),
                    required_capabilities=_capability_tuple(
                        raw.get("required_capabilities")
                    ),
                    matched_capabilities=_capability_tuple(
                        raw.get("matched_capabilities")
                    ),
                    context_pack_id=str(raw["context_pack_id"]),
                    token_allocation_step_id=str(
                        raw["token_allocation_step_id"]
                    ),
                    token_limit=_as_int(raw["token_limit"], "token_limit"),
                    depends_on=_string_tuple(raw.get("depends_on")),
                    wave=_as_int(raw["wave"], "wave"),
                    sequence=_as_int(raw["sequence"], "sequence"),
                    owned_files=_string_tuple(raw.get("owned_files")),
                    read_only_files=_string_tuple(
                        raw.get("read_only_files")
                    ),
                )
            )

        ownership: list[FileOwnership] = []
        for raw in raw_ownership:
            if not isinstance(raw, dict):
                continue
            raw_owner_node = raw.get("owner_node_id")
            raw_owner_agent = raw.get("owner_agent_id")
            raw_owner_step = raw.get("owner_step_id")
            ownership.append(
                FileOwnership(
                    relative_path=str(raw["relative_path"]),
                    owner_node_id=(
                        str(raw_owner_node)
                        if raw_owner_node is not None
                        else None
                    ),
                    owner_agent_id=(
                        str(raw_owner_agent)
                        if raw_owner_agent is not None
                        else None
                    ),
                    owner_step_id=(
                        str(raw_owner_step)
                        if raw_owner_step is not None
                        else None
                    ),
                    reader_agent_ids=_string_tuple(
                        raw.get("reader_agent_ids")
                    ),
                    reason=str(raw["reason"]),
                )
            )

        waves = tuple(
            _string_tuple(raw_wave)
            for raw_wave in raw_waves
            if isinstance(raw_wave, list)
        )
        graph = AgentRunGraph(
            schema_version=_as_int(
                value["schema_version"],
                "schema_version",
            ),
            graph_id=str(value["graph_id"]),
            plan_id=str(value["plan_id"]),
            selection_id=str(value["selection_id"]),
            budget_id=str(value["budget_id"]),
            task_id=str(value["task_id"]),
            project_root=str(value["project_root"]),
            created_at=str(value["created_at"]),
            status=cast(GraphStatus, str(value["status"])),
            registry=AgentRegistry(agents=tuple(agents)),
            nodes=tuple(nodes),
            ownership=tuple(ownership),
            waves=waves,
            protected_exclusions=_string_tuple(
                value.get("protected_exclusions")
            ),
        )
        graph.validate()
        return graph

    def _read(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
