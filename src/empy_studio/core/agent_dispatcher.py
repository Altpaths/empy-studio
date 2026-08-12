from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Final, Literal

from .context_selector import ContextPack, ContextSelection
from .planner import AgentRole, ExecutionPlan, PlanStep
from .token_budget import AgentTokenAllocation, TokenBudget

AgentCapability = Literal[
    "inspect-project",
    "read-context",
    "modify-frontend",
    "modify-backend",
    "audit-security",
    "verify-quality",
    "prepare-release",
    "bounded-execution",
]
GraphStatus = Literal["ready", "cancelled"]


ROLE_CAPABILITIES: Final[dict[AgentRole, tuple[AgentCapability, ...]]] = {
    "discovery": (
        "inspect-project",
        "read-context",
        "bounded-execution",
    ),
    "frontend": (
        "read-context",
        "modify-frontend",
        "bounded-execution",
    ),
    "backend": (
        "read-context",
        "modify-backend",
        "bounded-execution",
    ),
    "quality": (
        "read-context",
        "verify-quality",
        "bounded-execution",
    ),
    "security": (
        "read-context",
        "audit-security",
        "bounded-execution",
    ),
    "release": (
        "read-context",
        "prepare-release",
        "bounded-execution",
    ),
}

WRITING_ROLES: Final[frozenset[AgentRole]] = frozenset(
    {"frontend", "backend", "security", "release"}
)


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    display_name: str
    role: AgentRole
    capabilities: tuple[AgentCapability, ...]
    ownership_patterns: tuple[str, ...]
    priority: int = 100
    enabled: bool = True

    def validate(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id cannot be empty")
        if not self.display_name.strip():
            raise ValueError("agent display_name cannot be empty")
        if self.role not in ROLE_CAPABILITIES:
            raise ValueError(f"unsupported agent role: {self.role}")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("agent capabilities must be unique")
        if "bounded-execution" not in self.capabilities:
            raise ValueError("every dispatchable agent must support bounded execution")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRegistry:
    agents: tuple[AgentDefinition, ...]

    def validate(self) -> None:
        if not self.agents:
            raise ValueError("agent registry cannot be empty")
        identities = [agent.agent_id for agent in self.agents]
        if len(identities) != len(set(identities)):
            raise ValueError("agent registry IDs must be unique")
        for agent in self.agents:
            agent.validate()

    def get(self, agent_id: str) -> AgentDefinition:
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(f"unknown agent: {agent_id}")

    def match(
        self,
        *,
        role: AgentRole,
        required_capabilities: tuple[AgentCapability, ...],
    ) -> AgentDefinition:
        required = set(required_capabilities)
        candidates = [
            agent
            for agent in self.agents
            if agent.enabled
            and agent.role == role
            and required.issubset(agent.capabilities)
        ]
        if not candidates:
            raise ValueError(
                f"no enabled {role} agent satisfies capabilities: "
                f"{sorted(required)}"
            )
        candidates.sort(
            key=lambda agent: (
                -agent.priority,
                len(set(agent.capabilities) - required),
                agent.agent_id,
            )
        )
        return candidates[0]

    def to_dict(self) -> dict[str, object]:
        return {"agents": [agent.to_dict() for agent in self.agents]}


def default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry(
        agents=(
            AgentDefinition(
                agent_id="discovery-agent",
                display_name="Discovery Agent",
                role="discovery",
                capabilities=ROLE_CAPABILITIES["discovery"],
                ownership_patterns=(),
            ),
            AgentDefinition(
                agent_id="frontend-agent",
                display_name="Frontend Agent",
                role="frontend",
                capabilities=ROLE_CAPABILITIES["frontend"],
                ownership_patterns=(
                    "resources/views/**",
                    "resources/css/**",
                    "resources/js/**",
                    "public/**",
                    "frontend/**",
                    "templates/**",
                    "views/**",
                    "src/components/**",
                    "src/pages/**",
                    "src/**/*.css",
                    "src/**/*.scss",
                    "src/**/*.tsx",
                    "src/**/*.jsx",
                    "*.css",
                    "*.scss",
                    "*.html",
                    "**/*.html",
                    "*.htm",
                    "**/*.htm",
                ),
            ),
            AgentDefinition(
                agent_id="backend-agent",
                display_name="Backend Agent",
                role="backend",
                capabilities=ROLE_CAPABILITIES["backend"],
                ownership_patterns=(
                    "app/**",
                    "routes/**",
                    "database/**",
                    "api/**",
                    "server/**",
                    "src/**/*.py",
                    "src/**/*.php",
                    "src/**/*.go",
                    "src/**/*.rs",
                    "src/**/*.java",
                    "src/**/*.ts",
                    "src/**/*.js",
                    "src/*.py",
                    "src/*.php",
                    "src/*.js",
                    "lib/**",
                    "README.md",
                    "*.md",
                    "docs/**",
                    "*.php",
                    "**/*.php",
                ),
            ),
            AgentDefinition(
                agent_id="security-agent",
                display_name="Security Agent",
                role="security",
                capabilities=ROLE_CAPABILITIES["security"],
                ownership_patterns=(
                    "security/**",
                    "auth/**",
                    "middleware/**",
                    "**/auth.py",
                    "**/auth.php",
                    "**/permissions.py",
                    "**/policies/**",
                ),
            ),
            AgentDefinition(
                agent_id="quality-agent",
                display_name="Quality Agent",
                role="quality",
                capabilities=ROLE_CAPABILITIES["quality"],
                ownership_patterns=(),
            ),
            AgentDefinition(
                agent_id="release-agent",
                display_name="Release Agent",
                role="release",
                capabilities=ROLE_CAPABILITIES["release"],
                ownership_patterns=(
                    ".github/workflows/**",
                    "CHANGELOG.md",
                    "pyproject.toml",
                    "package.json",
                    "Dockerfile",
                    "docs/release*",
                    "release/**",
                ),
            ),
        )
    )
    registry.validate()
    return registry


@dataclass(frozen=True)
class FileOwnership:
    relative_path: str
    owner_node_id: str | None
    owner_agent_id: str | None
    owner_step_id: str | None
    reader_agent_ids: tuple[str, ...]
    reason: str

    def validate(self) -> None:
        if not self.relative_path:
            raise ValueError("owned file path cannot be empty")
        owner_values = (
            self.owner_node_id,
            self.owner_agent_id,
            self.owner_step_id,
        )
        if any(value is None for value in owner_values) and not all(
            value is None for value in owner_values
        ):
            raise ValueError("file ownership identity must be complete or empty")
        if len(set(self.reader_agent_ids)) != len(self.reader_agent_ids):
            raise ValueError("reader agent IDs must be unique")
        if not self.reason:
            raise ValueError("file ownership reason cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRunNode:
    node_id: str
    step_id: str
    title: str
    objective: str
    agent_id: str
    agent_role: AgentRole
    required_capabilities: tuple[AgentCapability, ...]
    matched_capabilities: tuple[AgentCapability, ...]
    context_pack_id: str
    token_allocation_step_id: str
    token_limit: int
    depends_on: tuple[str, ...]
    wave: int
    sequence: int
    owned_files: tuple[str, ...]
    read_only_files: tuple[str, ...]

    def validate(self) -> None:
        if not self.node_id or not self.step_id or not self.agent_id:
            raise ValueError("agent run node identity cannot be empty")
        if self.token_limit < 1:
            raise ValueError("agent run node token limit must be positive")
        if self.wave < 1 or self.sequence < 1:
            raise ValueError("agent run node ordering must be positive")
        if self.step_id != self.token_allocation_step_id:
            raise ValueError("node and token allocation step IDs do not match")
        if not set(self.required_capabilities).issubset(self.matched_capabilities):
            raise ValueError("agent does not satisfy required capabilities")
        if set(self.owned_files) & set(self.read_only_files):
            raise ValueError("a node cannot own and read the same file")
        if self.agent_role not in WRITING_ROLES and self.owned_files:
            raise ValueError("read-only agent role cannot own files")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRunGraph:
    schema_version: int
    graph_id: str
    plan_id: str
    selection_id: str
    budget_id: str
    task_id: str
    project_root: str
    created_at: str
    status: GraphStatus
    registry: AgentRegistry
    nodes: tuple[AgentRunNode, ...]
    ownership: tuple[FileOwnership, ...]
    waves: tuple[tuple[str, ...], ...]
    protected_exclusions: tuple[str, ...]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported agent-run-graph schema")
        if not all(
            (
                self.graph_id,
                self.plan_id,
                self.selection_id,
                self.budget_id,
                self.task_id,
                self.project_root,
            )
        ):
            raise ValueError("agent run graph identity cannot be empty")
        if self.status not in {"ready", "cancelled"}:
            raise ValueError(f"unsupported graph status: {self.status}")
        self.registry.validate()
        if not self.nodes:
            raise ValueError("agent run graph must contain nodes")

        node_ids = {node.node_id for node in self.nodes}
        step_ids = {node.step_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("agent run node IDs must be unique")
        if len(step_ids) != len(self.nodes):
            raise ValueError("agent run step IDs must be unique")

        registry_ids = {agent.agent_id for agent in self.registry.agents}
        protected = set(self.protected_exclusions)
        for node in self.nodes:
            node.validate()
            if node.agent_id not in registry_ids:
                raise ValueError("run node references an unregistered agent")
            agent = self.registry.get(node.agent_id)
            if not agent.enabled or agent.role != node.agent_role:
                raise ValueError("run node references an irrelevant agent")
            if set(node.depends_on) - node_ids:
                raise ValueError("run node contains an unknown dependency")
            if node.node_id in node.depends_on:
                raise ValueError("run node cannot depend on itself")
            if protected & (set(node.owned_files) | set(node.read_only_files)):
                raise ValueError("protected file reached an agent run node")

        flattened_waves = tuple(node_id for wave in self.waves for node_id in wave)
        if len(flattened_waves) != len(set(flattened_waves)):
            raise ValueError("agent run waves contain duplicate nodes")
        if set(flattened_waves) != node_ids:
            raise ValueError("agent run waves do not cover every node")
        wave_by_node = {
            node_id: wave_index
            for wave_index, wave in enumerate(self.waves, start=1)
            for node_id in wave
        }
        for node in self.nodes:
            if node.wave != wave_by_node[node.node_id]:
                raise ValueError("node wave metadata is inconsistent")
            if any(wave_by_node[dependency] >= node.wave for dependency in node.depends_on):
                raise ValueError("dependency sequencing is invalid")

        ownership_paths = [item.relative_path for item in self.ownership]
        if len(ownership_paths) != len(set(ownership_paths)):
            raise ValueError("each file must have one ownership record")
        node_by_id = {node.node_id: node for node in self.nodes}
        for item in self.ownership:
            item.validate()
            if item.relative_path in protected:
                raise ValueError("protected file cannot have an ownership record")
            if item.owner_node_id is None:
                continue
            if item.owner_node_id not in node_by_id:
                raise ValueError("file owner node is unknown")
            owner = node_by_id[item.owner_node_id]
            if item.owner_agent_id != owner.agent_id or item.owner_step_id != owner.step_id:
                raise ValueError("file owner identity is inconsistent")
            if item.relative_path not in owner.owned_files:
                raise ValueError("file ownership is missing from owner node")

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "registry": self.registry.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "ownership": [item.to_dict() for item in self.ownership],
            "waves": [list(wave) for wave in self.waves],
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_capabilities(step: PlanStep) -> tuple[AgentCapability, ...]:
    try:
        return ROLE_CAPABILITIES[step.suggested_agent]
    except KeyError as exc:
        raise ValueError(f"unsupported planned role: {step.suggested_agent}") from exc


def _execution_waves(steps: tuple[PlanStep, ...]) -> tuple[tuple[str, ...], ...]:
    pending = {step.step_id: set(step.depends_on) for step in steps}
    known = set(pending)
    for step_id, dependencies in pending.items():
        unknown = dependencies - known
        if unknown:
            raise ValueError(f"step {step_id} has unknown dependencies: {sorted(unknown)}")
        if step_id in dependencies:
            raise ValueError(f"step {step_id} cannot depend on itself")

    waves: list[tuple[str, ...]] = []
    completed: set[str] = set()
    while pending:
        ready = tuple(
            sorted(
                step_id
                for step_id, dependencies in pending.items()
                if dependencies.issubset(completed)
            )
        )
        if not ready:
            raise ValueError("agent run graph contains a dependency cycle")
        waves.append(ready)
        completed.update(ready)
        for step_id in ready:
            pending.pop(step_id)
    return tuple(waves)


def _pattern_specificity(pattern: str) -> int:
    return len(pattern.replace("*", "").replace("?", ""))


def _ownership_score(
    *,
    agent: AgentDefinition,
    relative_path: str,
    context_score: int,
    sequence: int,
) -> tuple[int, int, int]:
    pattern_score = max(
        (
            _pattern_specificity(pattern)
            for pattern in agent.ownership_patterns
            if fnmatch.fnmatch(relative_path, pattern)
        ),
        default=0,
    )
    return pattern_score, context_score, -sequence


def _matches_ownership_pattern(agent: AgentDefinition, relative_path: str) -> bool:
    return any(
        fnmatch.fnmatch(relative_path, pattern)
        for pattern in agent.ownership_patterns
    )


def _pack_by_step(selection: ContextSelection) -> dict[str, ContextPack]:
    values = {pack.step_id: pack for pack in selection.packs}
    if len(values) != len(selection.packs):
        raise ValueError("context selection contains duplicate step packs")
    return values


def _allocation_by_step(budget: TokenBudget) -> dict[str, AgentTokenAllocation]:
    values = {allocation.step_id: allocation for allocation in budget.allocations}
    if len(values) != len(budget.allocations):
        raise ValueError("token budget contains duplicate step allocations")
    return values


def _build_ownership(
    *,
    plan: ExecutionPlan,
    selection: ContextSelection,
    assignments: dict[str, AgentDefinition],
) -> tuple[FileOwnership, ...]:
    packs = _pack_by_step(selection)
    sequence_by_step = {
        step.step_id: index for index, step in enumerate(plan.steps, start=1)
    }
    file_candidates: dict[str, list[tuple[str, int]]] = {}
    readers: dict[str, set[str]] = {}

    for step in plan.steps:
        agent = assignments[step.step_id]
        pack = packs[step.step_id]
        for context_file in pack.files:
            readers.setdefault(context_file.relative_path, set()).add(agent.agent_id)
            if (
                step.suggested_agent in WRITING_ROLES
                and _matches_ownership_pattern(agent, context_file.relative_path)
            ):
                file_candidates.setdefault(context_file.relative_path, []).append(
                    (step.step_id, context_file.score)
                )

    ownership: list[FileOwnership] = []
    all_paths = sorted(readers)
    for relative_path in all_paths:
        candidates = file_candidates.get(relative_path, [])
        if not candidates:
            ownership.append(
                FileOwnership(
                    relative_path=relative_path,
                    owner_node_id=None,
                    owner_agent_id=None,
                    owner_step_id=None,
                    reader_agent_ids=tuple(sorted(readers[relative_path])),
                    reason="read-only context; no implementation step requires ownership",
                )
            )
            continue

        ranked = sorted(
            candidates,
            key=lambda item: _ownership_score(
                agent=assignments[item[0]],
                relative_path=relative_path,
                context_score=item[1],
                sequence=sequence_by_step[item[0]],
            ),
            reverse=True,
        )
        owner_step_id, _score = ranked[0]
        owner = assignments[owner_step_id]
        reader_ids = set(readers[relative_path])
        reader_ids.discard(owner.agent_id)
        ownership.append(
            FileOwnership(
                relative_path=relative_path,
                owner_node_id=f"node-{owner_step_id}",
                owner_agent_id=owner.agent_id,
                owner_step_id=owner_step_id,
                reader_agent_ids=tuple(sorted(reader_ids)),
                reason=(
                    f"single writer selected for {owner.role} scope by "
                    "ownership pattern, context score, and plan order"
                ),
            )
        )
    return tuple(ownership)


def build_agent_run_graph(
    *,
    plan: ExecutionPlan,
    selection: ContextSelection,
    budget: TokenBudget,
    registry: AgentRegistry | None = None,
) -> AgentRunGraph:
    plan.validate()
    selection.validate()
    budget.validate()
    selected_registry = registry or default_agent_registry()
    selected_registry.validate()

    if plan.status != "approved":
        raise ValueError("agent dispatch requires an approved plan")
    if budget.status != "locked":
        raise ValueError("agent dispatch requires a locked token budget")
    if selection.plan_id != plan.plan_id or budget.plan_id != plan.plan_id:
        raise ValueError("plan, context selection, and token budget do not match")
    if budget.selection_id != selection.selection_id:
        raise ValueError("context selection and token budget do not match")
    if not (plan.task_id == selection.task_id == budget.task_id):
        raise ValueError("task IDs do not match")
    if not (plan.project_root == selection.project_root == budget.project_root):
        raise ValueError("project roots do not match")

    packs = _pack_by_step(selection)
    allocations = _allocation_by_step(budget)
    plan_step_ids = {step.step_id for step in plan.steps}
    if set(packs) != plan_step_ids:
        raise ValueError("context packs do not cover every plan step")
    if set(allocations) != plan_step_ids:
        raise ValueError("token allocations do not cover every plan step")

    assignments: dict[str, AgentDefinition] = {}
    for step in plan.steps:
        required = _required_capabilities(step)
        assignments[step.step_id] = selected_registry.match(
            role=step.suggested_agent,
            required_capabilities=required,
        )

    ownership = _build_ownership(
        plan=plan,
        selection=selection,
        assignments=assignments,
    )
    waves_by_step = _execution_waves(plan.steps)
    wave_number = {
        step_id: index
        for index, wave in enumerate(waves_by_step, start=1)
        for step_id in wave
    }
    node_id_by_step = {step.step_id: f"node-{step.step_id}" for step in plan.steps}

    nodes: list[AgentRunNode] = []
    for sequence, step in enumerate(plan.steps, start=1):
        agent = assignments[step.step_id]
        pack = packs[step.step_id]
        allocation = allocations[step.step_id]
        owned_files = tuple(
            item.relative_path
            for item in ownership
            if item.owner_step_id == step.step_id
        )
        pack_paths = {item.relative_path for item in pack.files}
        read_only_files = tuple(sorted(pack_paths - set(owned_files)))
        required = _required_capabilities(step)
        nodes.append(
            AgentRunNode(
                node_id=node_id_by_step[step.step_id],
                step_id=step.step_id,
                title=step.title,
                objective=step.objective,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                required_capabilities=required,
                matched_capabilities=tuple(
                    capability
                    for capability in agent.capabilities
                    if capability in required
                ),
                context_pack_id=pack.pack_id,
                token_allocation_step_id=allocation.step_id,
                token_limit=allocation.total_limit_tokens,
                depends_on=tuple(node_id_by_step[item] for item in step.depends_on),
                wave=wave_number[step.step_id],
                sequence=sequence,
                owned_files=owned_files,
                read_only_files=read_only_files,
            )
        )

    writing_nodes = tuple(
        node
        for node in nodes
        if node.agent_role in WRITING_ROLES
    )
    if writing_nodes and not any(node.owned_files for node in writing_nodes):
        roles = ", ".join(sorted({node.agent_role for node in writing_nodes}))
        raise ValueError(
            "approved implementation plan has no writable files for "
            f"writing roles ({roles}); refine the task scope or project index"
        )

    node_waves = tuple(
        tuple(node_id_by_step[step_id] for step_id in wave)
        for wave in waves_by_step
    )
    protected_exclusions = tuple(
        sorted(
            item.relative_path
            for item in selection.exclusions
            if item.protected
        )
    )
    fingerprint = json.dumps(
        {
            "plan_id": plan.plan_id,
            "selection_id": selection.selection_id,
            "budget_id": budget.budget_id,
            "nodes": [node.to_dict() for node in nodes],
            "ownership": [item.to_dict() for item in ownership],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    graph = AgentRunGraph(
        schema_version=1,
        graph_id=hashlib.sha256(fingerprint).hexdigest()[:20],
        plan_id=plan.plan_id,
        selection_id=selection.selection_id,
        budget_id=budget.budget_id,
        task_id=plan.task_id,
        project_root=plan.project_root,
        created_at=_utc_now(),
        status="ready",
        registry=selected_registry,
        nodes=tuple(nodes),
        ownership=ownership,
        waves=node_waves,
        protected_exclusions=protected_exclusions,
    )
    graph.validate()
    return graph
