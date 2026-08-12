from __future__ import annotations

import subprocess
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from empy_studio.core import (
    AgentRunGraph,
    AgentRunNode,
    ContextPack,
    ContextSelection,
    DriverExecutionRequest,
    ProductTask,
    ProjectDescriptor,
    TokenBudget,
)
from empy_studio.token_usage import TokenUsage

from .codex import (
    CodexDriver,
    CodexErrorCode,
    CodexInstallation,
    CodexNodeExecution,
    CodexNodeStatus,
    CodexProgressEvent,
)

CodexRunStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "unavailable",
]
CodexWaveMode = Literal["serial", "parallel"]
RunProgressCallback = Callable[[CodexProgressEvent], None]


@dataclass(frozen=True)
class _GitSnapshot:
    head: str
    status: dict[str, str]


@dataclass(frozen=True)
class CodexWaveExecution:
    wave: int
    node_ids: tuple[str, ...]
    mode: CodexWaveMode
    capacity: int
    started_at: str
    finished_at: str

    def validate(self) -> None:
        if self.wave < 1 or not self.node_ids:
            raise ValueError("Codex wave execution identity is invalid")
        if self.mode not in {"serial", "parallel"}:
            raise ValueError("unsupported Codex wave execution mode")
        if self.capacity < 1:
            raise ValueError("Codex wave capacity must be positive")
        if not self.started_at or not self.finished_at:
            raise ValueError("Codex wave execution timestamps cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CodexNodeDriver(Protocol):
    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        ...

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress: RunProgressCallback | None = None,
    ) -> CodexNodeExecution:
        ...

    def cancel(self) -> None:
        ...


@dataclass(frozen=True)
class CodexGraphExecution:
    schema_version: int
    run_id: str
    graph_id: str
    task_id: str
    project_root: str
    provider: str
    status: CodexRunStatus
    started_at: str
    finished_at: str
    installation: CodexInstallation
    node_results: tuple[CodexNodeExecution, ...]
    events: tuple[CodexProgressEvent, ...]
    error_code: CodexErrorCode | None = None
    error_message: str | None = None
    usage: TokenUsage | None = None
    schedule: tuple[CodexWaveExecution, ...] = ()

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Codex graph execution schema")
        if not all((self.run_id, self.graph_id, self.task_id, self.project_root, self.provider)):
            raise ValueError("Codex graph execution identity cannot be empty")
        if self.status not in {
            "running",
            "completed",
            "failed",
            "cancelled",
            "timed_out",
            "unavailable",
        }:
            raise ValueError(f"unsupported Codex graph status: {self.status}")
        self.installation.validate()
        for node in self.node_results:
            node.validate()
        for event in self.events:
            event.validate()
        for wave in self.schedule:
            wave.validate()
        if self.status == "completed" and any(
            node.status != "completed" for node in self.node_results
        ):
            raise ValueError("completed Codex graph run contains incomplete nodes")
        if (
            self.status in {"failed", "cancelled", "timed_out", "unavailable"}
            and (self.error_code is None or not self.error_message)
        ):
            raise ValueError(
                "non-completed Codex graph run requires mapped error details"
            )

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["installation"] = self.installation.to_dict()
        value["node_results"] = [item.to_dict() for item in self.node_results]
        value["events"] = [item.to_dict() for item in self.events]
        value["usage"] = self.usage.to_dict() if self.usage is not None else None
        value["schedule"] = [item.to_dict() for item in self.schedule]
        return value


def build_codex_node_prompt(
    *,
    graph: AgentRunGraph,
    selection: ContextSelection,
    node: AgentRunNode,
    task: ProductTask | None = None,
) -> str:
    graph.validate()
    selection.validate()
    if task is not None:
        task.validate()
        if task.task_id != graph.task_id:
            raise ValueError("product task and agent graph do not match")
        if Path(task.project_root).expanduser().resolve() != Path(graph.project_root).expanduser().resolve():
            raise ValueError("product task and agent graph project roots do not match")
    if graph.selection_id != selection.selection_id:
        raise ValueError("agent graph and context selection do not match")
    pack = _pack_for_node(selection, node)
    owned = "\n".join(f"- {path}" for path in node.owned_files) or "- None. This is a read-only node."
    read_only = "\n".join(f"- {path}" for path in node.read_only_files) or "- None"
    protected = (
        "\n".join(f"- {path}" for path in graph.protected_exclusions)
        or "- No protected path names were exposed to this node."
    )
    context_sections = []
    for item in pack.files:
        mode = "OWNED" if item.relative_path in node.owned_files else "READ ONLY"
        truncation = " (truncated)" if item.truncated else ""
        context_sections.append(
            f"## {item.relative_path} [{mode}]{truncation}\n"
            f"Score: {item.score}; reasons: {', '.join(item.reasons)}\n\n"
            f"```text\n{item.content.rstrip()}\n```"
    )
    context = "\n\n".join(context_sections) or "No file content was selected for this node."
    task_contract = (
        "## Approved user task\n"
        f"Task ID: {task.task_id}\n"
        f"Task kind: {task.kind}\n"
        f"Task title: {task.title}\n"
        f"Task objective: {task.objective}\n\n"
        "### Requirements\n"
        + "\n".join(f"- {item}" for item in task.requirements)
        + "\n\n### Constraints\n"
        + ("\n".join(f"- {item}" for item in task.constraints) or "- None")
        + "\n\n### Definition of done\n"
        + "\n".join(f"- {item}" for item in task.definition_of_done)
        + "\n"
        if task is not None
        else (
            "## Approved user task\n"
            "The task contract was not materialized for this compatibility call. "
            "Follow the bounded node objective only.\n"
        )
    )
    return (
        "# Empy Studio approved Codex execution\n\n"
        "Execute exactly one approved Agent Run Graph node. Do not expand the scope.\n\n"
        f"{task_contract}\n"
        f"Project: {selection.project_brain.display_name}\n"
        f"Project type: {selection.project_brain.project_type}\n"
        f"Project summary: {selection.project_brain.summary}\n"
        f"Graph ID: {graph.graph_id}\n"
        f"Node ID: {node.node_id}\n"
        f"Agent role: {node.agent_role}\n"
        f"Step: {node.title}\n"
        f"Objective: {node.objective}\n"
        f"Provider-neutral local estimate recorded by Empy: {node.token_limit}\n\n"
        "## Non-negotiable execution rules\n"
        "1. Work only inside the selected project root.\n"
        "2. Modify only files listed under OWNED FILES.\n"
        "3. Treat READ-ONLY FILES as context; do not modify them.\n"
        "4. Do not read or modify protected paths.\n"
        "5. Do not commit, push, merge, tag, publish, or change Git remotes.\n"
        "6. Do not wait for interactive approval. Stop and explain if the task cannot be completed safely.\n"
        "7. Keep the implementation bounded to this node and its objective.\n\n"
        f"## Owned files\n{owned}\n\n"
        f"## Read-only files\n{read_only}\n\n"
        f"## Protected paths\n{protected}\n\n"
        f"## Bounded context pack\n{context}\n\n"
        "## Verification handoff\n"
        "Empy will run project-aware, allowlisted verification after the Agent graph. "
        "Writing nodes must not spend provider time running tests, builds, lint, or "
        "type checks; record those checks for the Quality node unless verification "
        "itself is the approved objective. "
        "Quality nodes must inspect the current working tree and current file contents "
        "after upstream nodes finish; the bounded context pack is only a hint and may "
        "be stale. Do not report a remaining risk from the initial context unless it "
        "is still observable now. "
        "Report checks actually run and unresolved risks; do not invent arbitrary commands "
        "or bypass Empy verification.\n\n"
        "## Required final message\n"
        "Report: work completed, files changed, checks run, remaining risks, "
        "and whether the node objective passed.\n"
    )


class CodexGraphRuntime:
    """Execute an approved Agent Run Graph through one production Codex driver."""

    def __init__(
        self,
        *,
        driver: CodexNodeDriver | None = None,
        run_root: str | Path,
        timeout_seconds: int = 1800,
        max_parallel_nodes: int = 2,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if max_parallel_nodes < 1:
            raise ValueError("max_parallel_nodes must be positive")
        self.driver = driver or CodexDriver(artifact_root=run_root)
        self.run_root = Path(run_root).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.max_parallel_nodes = max_parallel_nodes
        self._cancel_requested = threading.Event()
        self._lifecycle_lock = threading.Lock()

    def _execute_node(
        self,
        *,
        graph: AgentRunGraph,
        selection: ContextSelection,
        project: ProjectDescriptor,
        task: ProductTask | None,
        node: AgentRunNode,
        run_id: str,
        report: RunProgressCallback,
        audit_snapshot: bool,
    ) -> CodexNodeExecution:
        prompt = build_codex_node_prompt(
            graph=graph,
            selection=selection,
            node=node,
            task=task,
        )
        request = DriverExecutionRequest(
            project=project,
            task_id=f"{graph.task_id}:{node.step_id}",
            prompt=prompt,
            allowed_paths=node.owned_files,
            timeout_seconds=self.timeout_seconds,
        )
        before_snapshot = self._git_snapshot(project.root) if audit_snapshot else None
        node_result = self.driver.execute_streaming(
            request,
            node_id=node.node_id,
            artifact_dir=self.run_root / run_id / "nodes" / node.node_id,
            on_progress=report,
        )
        after_snapshot = self._git_snapshot(project.root) if audit_snapshot else None
        audited_changes = self._snapshot_delta(before_snapshot, after_snapshot)
        provider_changes = {
            self._normalize_changed_path(path, project.root)
            for path in node_result.changed_files
        }
        changed_files = tuple(sorted(provider_changes | audited_changes))
        node_result = replace(node_result, changed_files=changed_files)

        scope_errors: list[str] = []
        unauthorized = tuple(
            path
            for path in changed_files
            if not self._path_is_owned(path, node.owned_files)
        )
        if unauthorized:
            scope_errors.append(
                "Codex changed files outside this node's ownership: "
                + ", ".join(unauthorized)
            )
        if (
            before_snapshot is not None
            and after_snapshot is not None
            and before_snapshot.head != after_snapshot.head
        ):
            scope_errors.append(
                "Codex changed Git history even though commits are forbidden."
            )
        if scope_errors:
            error_message = " ".join(scope_errors)
            node_result = replace(
                node_result,
                status="failed",
                summary="Empy stopped the run after a scope audit failure.",
                error_code="scope_violation",
                error_message=error_message,
            )
            report(
                CodexProgressEvent(
                    timestamp=self._utc_now(),
                    level="error",
                    event_type="run.scope_violation",
                    message=error_message,
                    node_id=node.node_id,
                )
            )
        node_result.validate()
        return node_result

    def _can_parallelize(self, nodes: tuple[AgentRunNode, ...]) -> bool:
        if len(nodes) < 2 or self.max_parallel_nodes < 2:
            return False
        if not bool(getattr(self.driver, "supports_parallel_nodes", False)):
            return False
        owned: list[str] = [path for node in nodes for path in node.owned_files]
        return len(owned) == len(set(owned))

    def run(
        self,
        *,
        graph: AgentRunGraph,
        selection: ContextSelection,
        budget: TokenBudget,
        project: ProjectDescriptor,
        task: ProductTask | None = None,
        on_progress: RunProgressCallback | None = None,
    ) -> CodexGraphExecution:
        self._validate_inputs(graph, selection, budget, project, task)
        with self._lifecycle_lock:
            cancelled_before_start = self._cancel_requested.is_set()
            if not cancelled_before_start:
                begin_run = getattr(self.driver, "begin_run", None)
                if callable(begin_run):
                    begin_run()
        installation = self.driver.inspect_installation(refresh=True)
        run_id = uuid.uuid4().hex
        started_at = self._utc_now()
        events: list[CodexProgressEvent] = []
        event_lock = threading.Lock()

        def report(event: CodexProgressEvent) -> None:
            with event_lock:
                events.append(event)
            if on_progress is not None:
                on_progress(event)

        if cancelled_before_start:
            message = "The user cancelled the Codex graph run before it started."
            report(
                CodexProgressEvent(
                    timestamp=self._utc_now(),
                    level="warning",
                    event_type="run.cancelled",
                    message=message,
                )
            )
            result = CodexGraphExecution(
                schema_version=1,
                run_id=run_id,
                graph_id=graph.graph_id,
                task_id=graph.task_id,
                project_root=graph.project_root,
                provider="codex",
                status="cancelled",
                started_at=started_at,
                finished_at=self._utc_now(),
                installation=installation,
                node_results=(),
                events=tuple(events),
                error_code="cancelled",
                error_message=message,
            )
            result.validate()
            return result

        if not installation.ready:
            message = installation.message
            if installation.remediation:
                message = f"{message} {installation.remediation}"
            result = CodexGraphExecution(
                schema_version=1,
                run_id=run_id,
                graph_id=graph.graph_id,
                task_id=graph.task_id,
                project_root=graph.project_root,
                provider="codex",
                status="unavailable",
                started_at=started_at,
                finished_at=self._utc_now(),
                installation=installation,
                node_results=(),
                events=tuple(events),
                error_code=installation.terminal_error_code,
                error_message=message,
            )
            result.validate()
            return result

        initial_snapshot = self._git_snapshot(project.root)
        if initial_snapshot is not None and initial_snapshot.status:
            dirty_paths = ", ".join(sorted(initial_snapshot.status))
            message = (
                "Codex execution requires a clean Git worktree so Empy can "
                f"audit file ownership. Commit or restore these paths first: {dirty_paths}"
            )
            event = CodexProgressEvent(
                timestamp=self._utc_now(),
                level="error",
                event_type="run.dirty_worktree",
                message=message,
            )
            report(event)
            result = CodexGraphExecution(
                schema_version=1,
                run_id=run_id,
                graph_id=graph.graph_id,
                task_id=graph.task_id,
                project_root=graph.project_root,
                provider="codex",
                status="failed",
                started_at=started_at,
                finished_at=self._utc_now(),
                installation=installation,
                node_results=(),
                events=tuple(events),
                error_code="dirty_worktree",
                error_message=message,
            )
            result.validate()
            return result

        node_by_id = {node.node_id: node for node in graph.nodes}
        completed_nodes: list[CodexNodeExecution] = []
        terminal_status: CodexRunStatus = "completed"
        terminal_error_code: CodexErrorCode | None = None
        terminal_error_message: str | None = None
        stop = False
        schedule: list[CodexWaveExecution] = []

        for wave_number, raw_wave in enumerate(graph.waves, start=1):
            wave = tuple(raw_wave)
            if self._cancel_requested.is_set():
                terminal_status = "cancelled"
                terminal_error_code = "cancelled"
                terminal_error_message = "The user cancelled the Codex graph run."
                stop = True
                break
            wave_started_at = self._utc_now()
            nodes = tuple(node_by_id[node_id] for node_id in wave)
            can_parallelize = self._can_parallelize(nodes)
            wave_results: list[CodexNodeExecution] = []
            wave_snapshot = self._git_snapshot(project.root) if can_parallelize else None
            if can_parallelize:
                with ThreadPoolExecutor(
                    max_workers=min(self.max_parallel_nodes, len(nodes)),
                    thread_name_prefix="empy-codex-node",
                ) as executor:
                    futures = {
                        node.node_id: executor.submit(
                            self._execute_node,
                            graph=graph,
                            selection=selection,
                            project=project,
                            task=task,
                            node=node,
                            run_id=run_id,
                            report=report,
                            audit_snapshot=False,
                        )
                        for node in nodes
                    }
                    wave_results = [futures[node.node_id].result() for node in nodes]
                after_wave_snapshot = self._git_snapshot(project.root)
                audited_changes = self._snapshot_delta(
                    wave_snapshot,
                    after_wave_snapshot,
                )
                allowed_paths = {
                    path
                    for node in nodes
                    for path in node.owned_files
                }
                unauthorized = tuple(sorted(audited_changes - allowed_paths))
                history_changed = (
                    wave_snapshot is not None
                    and after_wave_snapshot is not None
                    and wave_snapshot.head != after_wave_snapshot.head
                )
                for index, node_result in enumerate(wave_results):
                    node = nodes[index]
                    owned_changes = set(node_result.changed_files) | (
                        audited_changes & set(node.owned_files)
                    )
                    wave_results[index] = replace(
                        node_result,
                        changed_files=tuple(sorted(owned_changes)),
                    )
                if unauthorized or history_changed:
                    scope_errors = []
                    if unauthorized:
                        scope_errors.append(
                            "Codex changed files outside this wave's ownership: "
                            + ", ".join(unauthorized)
                        )
                    if history_changed:
                        scope_errors.append(
                            "Codex changed Git history even though commits are forbidden."
                        )
                    error_message = " ".join(scope_errors)
                    first = wave_results[0]
                    wave_results[0] = replace(
                        first,
                        status="failed",
                        summary="Empy stopped the run after a scope audit failure.",
                        error_code="scope_violation",
                        error_message=error_message,
                    )
                    report(
                        CodexProgressEvent(
                            timestamp=self._utc_now(),
                            level="error",
                            event_type="run.scope_violation",
                            message=error_message,
                            node_id=nodes[0].node_id,
                        )
                    )
                    wave_results[0].validate()
            else:
                for node in nodes:
                    if self._cancel_requested.is_set():
                        terminal_status = "cancelled"
                        terminal_error_code = "cancelled"
                        terminal_error_message = "The user cancelled the Codex graph run."
                        stop = True
                        break
                    wave_results.append(
                        self._execute_node(
                            graph=graph,
                            selection=selection,
                            project=project,
                            task=task,
                            node=node,
                            run_id=run_id,
                            report=report,
                            audit_snapshot=True,
                        )
                    )
                    if wave_results[-1].status != "completed":
                        terminal_status = self._run_status_for_node(wave_results[-1].status)
                        terminal_error_code = wave_results[-1].error_code or "process_failed"
                        terminal_error_message = (
                            wave_results[-1].error_message or wave_results[-1].summary
                        )
                        stop = True
                        break

            completed_nodes.extend(wave_results)
            wave_finished_at = self._utc_now()
            schedule.append(
                CodexWaveExecution(
                    wave=wave_number,
                    node_ids=wave,
                    mode="parallel" if can_parallelize else "serial",
                    capacity=min(self.max_parallel_nodes, len(nodes))
                    if can_parallelize
                    else 1,
                    started_at=wave_started_at,
                    finished_at=wave_finished_at,
                )
            )
            if stop:
                break
            failed = next(
                (item for item in wave_results if item.status != "completed"),
                None,
            )
            if failed is not None:
                terminal_status = self._run_status_for_node(failed.status)
                terminal_error_code = failed.error_code or "process_failed"
                terminal_error_message = failed.error_message or failed.summary
                stop = True
                break

        executed_ids = {item.node_id for item in completed_nodes}
        if stop:
            for node in graph.nodes:
                if node.node_id in executed_ids:
                    continue
                completed_nodes.append(
                    self._skipped_result(
                        graph=graph,
                        node=node,
                        run_id=run_id,
                        reason=(
                            "Skipped because the run stopped before this "
                            "dependency-safe node could start."
                        ),
                    )
                )

        result = CodexGraphExecution(
            schema_version=1,
            run_id=run_id,
            graph_id=graph.graph_id,
            task_id=graph.task_id,
            project_root=graph.project_root,
            provider="codex",
            status=terminal_status,
            started_at=started_at,
            finished_at=self._utc_now(),
            installation=installation,
            node_results=tuple(completed_nodes),
            events=tuple(events),
            error_code=terminal_error_code,
            error_message=terminal_error_message,
            usage=TokenUsage.aggregate(
                (node.usage for node in completed_nodes),
                provider="codex",
            ),
            schedule=tuple(schedule),
        )
        result.validate()
        return result

    def cancel(self) -> None:
        with self._lifecycle_lock:
            self._cancel_requested.set()
        self.driver.cancel()

    @staticmethod
    def _validate_inputs(
        graph: AgentRunGraph,
        selection: ContextSelection,
        budget: TokenBudget,
        project: ProjectDescriptor,
        task: ProductTask | None = None,
    ) -> None:
        graph.validate()
        selection.validate()
        budget.validate()
        project.validate()
        if task is not None:
            task.validate()
            if task.task_id != graph.task_id:
                raise ValueError("product task and agent graph do not match")
            if Path(task.project_root).expanduser().resolve() != project.root.resolve():
                raise ValueError("product task and selected project do not match")
        if graph.status != "ready":
            raise ValueError("Codex execution requires a ready Agent Run Graph")
        if budget.status != "locked":
            raise ValueError("Codex execution requires a locked token budget")
        if not (
            graph.plan_id == selection.plan_id == budget.plan_id
            and graph.selection_id == selection.selection_id == budget.selection_id
            and graph.budget_id == budget.budget_id
        ):
            raise ValueError("Agent graph, context selection, and token budget do not match")
        if str(project.root.resolve()) != str(Path(graph.project_root).resolve()):
            raise ValueError("selected project does not match the Agent Run Graph")

    @staticmethod
    def _git_snapshot(root: Path) -> _GitSnapshot | None:
        try:
            worktree = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if worktree.returncode != 0 or worktree.stdout.strip() != "true":
                return None
            head_result = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            status_result = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                    "--",
                    ".",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if status_result.returncode != 0:
            return None
        head = head_result.stdout.strip() if head_result.returncode == 0 else "UNBORN"
        return _GitSnapshot(
            head=head,
            status=CodexGraphRuntime._parse_git_status(status_result.stdout),
        )

    @staticmethod
    def _normalize_changed_path(path: str, root: Path) -> str:
        normalized = path.replace("\\", "/")
        candidate = Path(normalized)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                return candidate.as_posix()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _parse_git_status(output: str) -> dict[str, str]:
        values: dict[str, str] = {}
        entries = output.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry or len(entry) < 4:
                continue
            status = entry[:2]
            path = entry[3:]
            if status[0] in {"R", "C"} and index < len(entries):
                target = entries[index]
                index += 1
                if target:
                    path = target
            values[path] = status
        return values

    @staticmethod
    def _snapshot_delta(
        before: _GitSnapshot | None,
        after: _GitSnapshot | None,
    ) -> set[str]:
        if before is None or after is None:
            return set()
        paths = set(before.status) | set(after.status)
        return {
            path
            for path in paths
            if before.status.get(path) != after.status.get(path)
        }

    @staticmethod
    def _path_is_owned(path: str, owned_files: tuple[str, ...]) -> bool:
        normalized = Path(path).as_posix().lstrip("./")
        for owned in owned_files:
            normalized_owned = Path(owned).as_posix().rstrip("/").lstrip("./")
            if normalized == normalized_owned:
                return True
            if owned.endswith("/") and normalized.startswith(f"{normalized_owned}/"):
                return True
        return False

    def _skipped_result(
        self,
        *,
        graph: AgentRunGraph,
        node: AgentRunNode,
        run_id: str,
        reason: str,
    ) -> CodexNodeExecution:
        node_dir = self.run_root / run_id / "nodes" / node.node_id
        timestamp = self._utc_now()
        result = CodexNodeExecution(
            node_id=node.node_id,
            task_id=f"{graph.task_id}:{node.step_id}",
            status="skipped",
            started_at=timestamp,
            finished_at=timestamp,
            return_code=None,
            thread_id=None,
            summary=reason,
            changed_files=(),
            event_count=0,
            events_path=str(node_dir / "events.jsonl"),
            stderr_path=str(node_dir / "stderr.log"),
            final_message_path=str(node_dir / "final-message.md"),
            command_path=str(node_dir / "command.json"),
        )
        result.validate()
        return result

    @staticmethod
    def _run_status_for_node(status: CodexNodeStatus) -> CodexRunStatus:
        mapping: dict[CodexNodeStatus, CodexRunStatus] = {
            "pending": "failed",
            "running": "failed",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "timed_out": "timed_out",
            "unavailable": "unavailable",
            "skipped": "failed",
        }
        return mapping[status]

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


def _pack_for_node(selection: ContextSelection, node: AgentRunNode) -> ContextPack:
    for pack in selection.packs:
        if pack.pack_id == node.context_pack_id and pack.step_id == node.step_id:
            return pack
    raise ValueError(f"context pack is missing for node {node.node_id}")
