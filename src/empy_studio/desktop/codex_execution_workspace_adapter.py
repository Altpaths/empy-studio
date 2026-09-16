from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from empy_studio.core import (
    ContextManifest,
    ContextManifestFile,
    LedgerEntry,
    RouteAttempt,
    RouteDecisionAction,
    RouteFailureClass,
    RouteReport,
    TaskLedgerSnapshot,
    UsageState,
)
from empy_studio.core.token_budget import ProviderBudgetReport, ProviderNodeBudgetReport
from empy_studio.drivers import (
    CodexAvailability,
    CodexErrorCode,
    CodexEventLevel,
    CodexGraphExecution,
    CodexInstallation,
    CodexNodeExecution,
    CodexNodeStatus,
    CodexProgressEvent,
    CodexRunStatus,
    CodexWaveExecution,
)
from empy_studio.token_usage import TokenUsage


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, field_name)


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _prompt_estimates(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        return ()
    estimates: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, dict) or "node_id" not in item:
            continue
        estimates.append(
            (str(item["node_id"]), _as_int(item.get("prompt_tokens", 0), "prompt_tokens"))
        )
    return tuple(estimates)


def _raw_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _usage(value: object) -> TokenUsage | None:
    if not isinstance(value, dict):
        return None
    return TokenUsage.from_dict({str(key): item for key, item in value.items()})


def _context_manifest(value: object) -> ContextManifest | None:
    if not isinstance(value, dict):
        return None
    raw_files = value.get("files", [])
    if not isinstance(raw_files, list):
        return None
    files = tuple(
        ContextManifestFile(
            relative_path=str(item["relative_path"]),
            sha256=str(item["sha256"]),
            selected_bytes=_as_int(item["selected_bytes"], "context.selected_bytes"),
            content_included=bool(item.get("content_included", False)),
        )
        for item in raw_files
        if isinstance(item, dict)
    )
    manifest = ContextManifest(
        schema_version=_as_int(value.get("schema_version", 1), "context.schema_version"),
        project_root=str(value["project_root"]),
        selection_id=str(value["selection_id"]),
        snapshot_sha256=str(value["snapshot_sha256"]),
        files=files,
        selected_bytes=_as_int(value["selected_bytes"], "context.selected_bytes"),
    )
    manifest.validate()
    return manifest


def _task_ledger(value: object) -> TaskLedgerSnapshot | None:
    if not isinstance(value, dict):
        return None
    raw_entries = value.get("entries", [])
    if not isinstance(raw_entries, list):
        raw_entries = []
    entries = tuple(
        LedgerEntry(
            operation_id=str(item["operation_id"]),
            provider_id=str(item["provider_id"]),
            reserved_tokens=_as_int(item["reserved_tokens"], "ledger.reserved_tokens"),
            charged_tokens=_as_int(item["charged_tokens"], "ledger.charged_tokens"),
            usage_state=cast(UsageState, str(item["usage_state"])),
            fresh_tokens=(
                _optional_int(item.get("fresh_tokens"), "ledger.fresh_tokens")
                if item.get("fresh_tokens") is not None else None
            ),
            cached_tokens=(
                _optional_int(item.get("cached_tokens"), "ledger.cached_tokens")
                if item.get("cached_tokens") is not None else None
            ),
            total_tokens=(
                _optional_int(item.get("total_tokens"), "ledger.total_tokens")
                if item.get("total_tokens") is not None else None
            ),
            status=str(item["status"]),
        )
        for item in raw_entries
        if isinstance(item, dict)
    )
    snapshot = TaskLedgerSnapshot(
        schema_version=_as_int(value.get("schema_version", 1), "ledger.schema_version"),
        total_limit_tokens=_as_int(value["total_limit_tokens"], "ledger.total"),
        fixed_commitment_tokens=_as_int(value.get("fixed_commitment_tokens", 0), "ledger.fixed"),
        charged_tokens=_as_int(value.get("charged_tokens", 0), "ledger.charged"),
        reserved_tokens=_as_int(value.get("reserved_tokens", 0), "ledger.reserved"),
        remaining_tokens=_as_int(value.get("remaining_tokens", 0), "ledger.remaining"),
        usage_complete=bool(value.get("usage_complete", False)),
        unknown_operation_ids=_string_tuple(value.get("unknown_operation_ids")),
        entries=entries,
    )
    snapshot.validate()
    return snapshot


def _route_report(value: object) -> RouteReport | None:
    if not isinstance(value, dict):
        return None
    raw_attempts = value.get("attempts", [])
    if not isinstance(raw_attempts, list):
        raw_attempts = []
    attempts = tuple(
        RouteAttempt(
            provider_id=str(item["provider_id"]),
            model=_optional_string(item.get("model")),
            attempt=_as_int(item["attempt"], "route.attempt"),
            status=str(item["status"]),
            failure_class=(
                cast(RouteFailureClass, str(item["failure_class"]))
                if item.get("failure_class") is not None
                else None
            ),
            error_code=_optional_string(item.get("error_code")),
            changed_files=_string_tuple(item.get("changed_files")),
            usage=_usage(item.get("usage")),
            usage_state=cast(UsageState, str(item.get("usage_state", "unknown"))),
        )
        for item in raw_attempts
        if isinstance(item, dict)
    )
    report = RouteReport(
        attempts=attempts,
        selected_provider_id=_optional_string(value.get("selected_provider_id")),
        switched=bool(value.get("switched", False)),
        decision=cast(RouteDecisionAction, str(value.get("decision", "stop"))),
        reason=str(value.get("reason", "No route attempt was made.")),
    )
    report.validate()
    return report


class CodexExecutionWorkspaceAdapter:
    """Persist Codex graph runs and their human-readable execution state."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace_root / "codex-runs.json"
        self.run_root = self.workspace_root / "runs"
        self.run_root.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: CodexGraphExecution) -> None:
        run.validate()
        existing = {
            str(item["run_id"]): item
            for item in self._read()
            if "run_id" in item
        }
        existing[run.run_id] = run.to_dict()
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

    def get_run(self, run_id: str) -> CodexGraphExecution | None:
        for value in reversed(self._read()):
            if value.get("run_id") == run_id:
                return self._from_dict(value)
        return None

    def get_for_graph(self, graph_id: str) -> CodexGraphExecution | None:
        matches = [
            value
            for value in self._read()
            if value.get("graph_id") == graph_id
        ]
        if not matches:
            return None
        return self._from_dict(matches[-1])

    def list_runs(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[CodexGraphExecution, ...]:
        values = self._read()
        if project_root is not None:
            values = [
                value
                for value in values
                if value.get("project_root") == project_root
            ]
        values.sort(key=lambda value: str(value.get("started_at", "")), reverse=True)
        return tuple(self._from_dict(value) for value in values)

    def _from_dict(self, value: dict[str, object]) -> CodexGraphExecution:
        raw_installation = value.get("installation")
        raw_nodes = value.get("node_results", [])
        raw_events = value.get("events", [])
        raw_schedule = value.get("schedule", [])
        if not isinstance(raw_installation, dict):
            raise TypeError("installation must be an object")
        if not isinstance(raw_nodes, list):
            raise TypeError("node_results must be a list")
        if not isinstance(raw_events, list):
            raise TypeError("events must be a list")
        if not isinstance(raw_schedule, list):
            raw_schedule = []

        installation = CodexInstallation(
            availability=cast(
                CodexAvailability,
                str(raw_installation["availability"]),
            ),
            executable=_optional_string(raw_installation.get("executable")),
            version=_optional_string(raw_installation.get("version")),
            authenticated=bool(raw_installation["authenticated"]),
            message=str(raw_installation["message"]),
            remediation=_optional_string(raw_installation.get("remediation")),
            error_code=(
                cast(CodexErrorCode, str(raw_installation["error_code"]))
                if raw_installation.get("error_code") is not None
                else None
            ),
        )

        nodes: list[CodexNodeExecution] = []
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            raw_error_code = raw.get("error_code")
            nodes.append(
                CodexNodeExecution(
                    node_id=str(raw["node_id"]),
                    task_id=str(raw["task_id"]),
                    status=cast(CodexNodeStatus, str(raw["status"])),
                    started_at=str(raw["started_at"]),
                    finished_at=str(raw["finished_at"]),
                    return_code=_optional_int(raw.get("return_code"), "return_code"),
                    thread_id=_optional_string(raw.get("thread_id")),
                    summary=str(raw["summary"]),
                    changed_files=_string_tuple(raw.get("changed_files")),
                    event_count=_as_int(raw["event_count"], "event_count"),
                    events_path=str(raw["events_path"]),
                    stderr_path=str(raw["stderr_path"]),
                    final_message_path=str(raw["final_message_path"]),
                    command_path=str(raw["command_path"]),
                    error_code=(
                        cast(CodexErrorCode, str(raw_error_code))
                        if raw_error_code is not None
                        else None
                    ),
                    error_message=_optional_string(raw.get("error_message")),
                    usage=_usage(raw.get("usage")),
                )
            )

        events: list[CodexProgressEvent] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            raw_node_id = raw.get("node_id")
            events.append(
                CodexProgressEvent(
                    timestamp=str(raw["timestamp"]),
                    level=cast(CodexEventLevel, str(raw["level"])),
                    event_type=str(raw["event_type"]),
                    message=str(raw["message"]),
                    node_id=(
                        str(raw_node_id)
                        if raw_node_id is not None
                        else None
                    ),
                    raw=_raw_dict(raw.get("raw")),
                )
            )

        schedule: list[CodexWaveExecution] = []
        for raw in raw_schedule:
            if not isinstance(raw, dict):
                continue
            schedule.append(
                CodexWaveExecution(
                    wave=_as_int(raw["wave"], "schedule.wave"),
                    node_ids=_string_tuple(raw.get("node_ids")),
                    mode=cast(Literal["serial", "parallel"], str(raw["mode"])),
                    capacity=_as_int(raw["capacity"], "schedule.capacity"),
                    started_at=str(raw["started_at"]),
                    finished_at=str(raw["finished_at"]),
                )
            )

        budget_report = None
        raw_budget = value.get("budget_accounting")
        if isinstance(raw_budget, dict):
            budget_report = ProviderBudgetReport(
                budget_id=str(raw_budget["budget_id"]),
                planned_total_limit_tokens=_as_int(raw_budget["planned_total_limit_tokens"], "budget.total"),
                nodes=tuple(ProviderNodeBudgetReport(**node) for node in raw_budget.get("nodes", [])),
            )
        raw_error_code = value.get("error_code")
        context_manifest = _context_manifest(value.get("context_manifest"))
        task_ledger = _task_ledger(value.get("task_ledger"))
        route_report = _route_report(value.get("route_report"))
        run = CodexGraphExecution(
            schema_version=_as_int(value["schema_version"], "schema_version"),
            run_id=str(value["run_id"]),
            graph_id=str(value["graph_id"]),
            task_id=str(value["task_id"]),
            project_root=str(value["project_root"]),
            provider=str(value["provider"]),
            status=cast(CodexRunStatus, str(value["status"])),
            started_at=str(value["started_at"]),
            finished_at=str(value["finished_at"]),
            installation=installation,
            node_results=tuple(nodes),
            events=tuple(events),
            error_code=(
                cast(CodexErrorCode, str(raw_error_code))
                if raw_error_code is not None
                else None
            ),
            error_message=_optional_string(value.get("error_message")),
            usage=_usage(value.get("usage")),
            schedule=tuple(schedule),
            budget_accounting=budget_report,
            prompt_estimates=_prompt_estimates(value.get("prompt_estimates")),
            context_manifest=context_manifest,
            task_ledger=task_ledger,
            route_report=route_report,
        )
        run.validate()
        return run

    def _read(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
