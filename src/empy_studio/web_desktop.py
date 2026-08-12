from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from empy_studio.benchmark import BenchmarkResult, run_local_benchmark
from empy_studio.core import (
    AgentRunGraph,
    ContextSelection,
    DefaultProjectService,
    ExecutionPlan,
    ProductTask,
    ProjectDetection,
    TaskKind,
    TokenBudget,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_product_task,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
    mark_ready_for_planning,
)
from empy_studio.core.project_brain import (
    ProjectBrainIndex,
    build_load_save_project_brain_index,
)
from empy_studio.desktop.codex_execution_workspace_adapter import (
    CodexExecutionWorkspaceAdapter,
)
from empy_studio.desktop.verification_workspace_adapter import (
    VerificationWorkspaceAdapter,
)
from empy_studio.drivers import (
    CodexDriver,
    CodexGraphExecution,
    CodexGraphRuntime,
    CodexProgressEvent,
)
from empy_studio.platform_support import default_workspace_root
from empy_studio.project_delivery import (
    MAX_UPLOAD_FILE_BYTES,
    MAX_UPLOAD_TOTAL_BYTES,
    ExportedProject,
    ImportedProject,
    checkpoint_accepted_changes,
    export_project_zip,
    import_project_archive,
    import_project_folder,
    safe_upload_relative_path,
    summarize_import_skips,
)
from empy_studio.review_workspace import ReviewReport, ReviewWorkspaceAdapter
from empy_studio.security_audit import redact_sensitive_output
from empy_studio.token_usage import TokenUsage
from empy_studio.user_errors import safe_user_error
from empy_studio.vault import initialize_vault
from empy_studio.verification_pipeline import (
    VerificationCancelled,
    VerificationEvent,
    VerificationReport,
    VerificationRuntime,
    VerificationTimedOut,
    finalize_verification,
    verification_contract_signature,
    verification_staleness_reason,
)
from empy_studio.workspace import SQLiteWorkspaceStore

WEB_ROOT = Path(__file__).with_name("web")
DEFAULT_CONSTRAINTS = (
    "Do not change unrelated features or business behavior.\n"
    "Do not read or modify secrets, environment files, logs, vendor, node_modules, or Git history.\n"
    "Do not commit, push, merge, tag, publish, or alter remotes."
)
DEFAULT_DEFINITION_OF_DONE = (
    "Every requested task is implemented.\n"
    "Only files required by the approved work are changed.\n"
    "Relevant tests, build, and lint checks pass when available.\n"
    "A readable review and complete project archive are produced."
)


def _content_type_for_asset(target: Path) -> str:
    stable_types = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "text/javascript",
        ".json": "application/json",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }
    return stable_types.get(target.suffix.lower()) or mimetypes.guess_type(
        target.name
    )[0] or "application/octet-stream"


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(cast(Any, value)))
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _safe_verification_detail(value: str, roots: tuple[Path, ...]) -> str:
    """Bound and redact verification output before exposing it to the browser."""

    detail = redact_sensitive_output(value.strip())
    for index, root in enumerate(roots):
        detail = detail.replace(str(root), "<project>" if index == 0 else "<workspace>")
    return detail[-1200:] if detail else "No diagnostic output was produced."


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, round((finished - started).total_seconds(), 3))


def _usage_summary(
    usage: TokenUsage | None,
    *,
    provider: str,
    status: str,
    estimated_tokens: int | None = None,
) -> dict[str, Any]:
    if usage is None:
        return {
            "provider": provider,
            "status": status,
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
            "total_tokens": None,
            "estimated_tokens": estimated_tokens,
            "available": False,
            "source": "not_reported",
        }
    return {
        "provider": provider,
        "status": status,
        "input_tokens": usage.input,
        "output_tokens": usage.output,
        "cached_input_tokens": usage.cached,
        "total_tokens": usage.total,
        "estimated_tokens": estimated_tokens,
        "available": usage.total > 0,
        "source": usage.source,
    }


def _split_task_lines(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    markers = (
        "do not",
        "don't",
        "must not",
        "should not",
        "without changing",
        "preserve",
        "نباید",
        "تغییر نده",
        "بدون تغییر",
        "حفظ شود",
    )
    requirements: list[str] = []
    constraints: list[str] = []
    for raw_line in raw.splitlines():
        # Users commonly put the action and its safety constraint in one
        # sentence. Split explicit clause separators first so a request such
        # as "audit the project; without changing the original" remains
        # actionable instead of being classified as constraints-only.
        for raw_clause in raw_line.replace("؛", ";").split(";"):
            line = raw_clause.strip(" -•\t")
            if not line:
                continue
            normalized = line.casefold()
            if any(normalized.startswith(marker) for marker in markers):
                constraints.append(line)
            else:
                requirements.append(line)
    return tuple(requirements), tuple(constraints)


@dataclass
class UploadSession:
    upload_id: str
    root: Path
    total_bytes: int = 0
    file_count: int = 0
    skipped_count: int = 0


@dataclass
class GuidedState:
    workspace_root: Path
    store: SQLiteWorkspaceStore = field(init=False)
    project_service: DefaultProjectService = field(default_factory=DefaultProjectService)
    active_project_id: str | None = None
    active_task_id: str | None = None
    language: str = "fa"
    phase: str = "project"
    message: str = ""
    message_level: str = "info"
    error: str | None = None
    continuation_context: str | None = None
    imported: ImportedProject | None = None
    import_report: dict[str, Any] | None = None
    detection: ProjectDetection | None = None
    task: ProductTask | None = None
    plan: ExecutionPlan | None = None
    context: ContextSelection | None = None
    budget: TokenBudget | None = None
    brain_index: ProjectBrainIndex | None = None
    benchmark: BenchmarkResult | None = None
    graph: AgentRunGraph | None = None
    run: CodexGraphExecution | None = None
    verification: VerificationReport | None = None
    review: ReviewReport | None = None
    export: ExportedProject | None = None
    logs: list[dict[str, str]] = field(default_factory=list)
    node_states: dict[str, str] = field(default_factory=dict)
    running: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    driver: CodexDriver = field(init=False, repr=False)
    review_store: ReviewWorkspaceAdapter = field(init=False, repr=False)
    execution_store: CodexExecutionWorkspaceAdapter = field(init=False, repr=False)
    verification_store: VerificationWorkspaceAdapter = field(init=False, repr=False)
    runtime: CodexGraphRuntime | None = field(init=False, default=None, repr=False)
    cancel_event: threading.Event | None = field(init=False, default=None, repr=False)
    upload_sessions: dict[str, UploadSession] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.workspace_root = self.workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteWorkspaceStore(self.workspace_root / "workspace.sqlite3")
        self.driver = CodexDriver(artifact_root=self.workspace_root / "codex-runs")
        self.review_store = ReviewWorkspaceAdapter(self.workspace_root)
        self.execution_store = CodexExecutionWorkspaceAdapter(self.workspace_root)
        self.verification_store = VerificationWorkspaceAdapter(self.workspace_root)
        saved_language = self.store.get_setting("language", "fa")
        self.language = saved_language if saved_language in {"fa", "en"} else "fa"
        saved_project = self.store.get_setting("active_project_id")
        if isinstance(saved_project, str):
            self.select_project(saved_project, restore=True)
            saved_task = self.store.get_setting("active_task_id")
            if isinstance(saved_task, str):
                try:
                    self.select_task(saved_task, restore=True)
                except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                    self.store.set_setting("active_task_id", None)

    def add_log(self, message: str, level: str = "info") -> None:
        with self.lock:
            self.logs.append({"time": _now(), "level": level, "text": message.rstrip()})
            self.logs = self.logs[-300:]

    def _project_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for project in self.store.list_projects():
            records.append(
                {
                    "id": project.project_id,
                    "name": project.display_name,
                    "root": project.root,
                    "type": project.project_type,
                    "last_opened_at": project.last_opened_at,
                        "tasks": [
                        {
                            "id": task.task_id,
                            "title": task.title,
                            "status": task.status,
                            "updated_at": task.updated_at,
                        }
                        for task in self.store.list_tasks(project.project_id)
                    ],
                    "releases": [
                        {
                            "id": release.release_id,
                            "task_id": release.task_id,
                            "sha256": release.sha256,
                            "file_count": release.file_count,
                            "verified": release.verified,
                            "archive_path": release.archive_path,
                            "created_at": release.created_at,
                        }
                        for release in self.store.list_releases(project.project_id)
                    ],
                }
            )
        return records

    def _active_project(self) -> dict[str, Any] | None:
        if self.active_project_id is None:
            return None
        for project in self._project_records():
            if project["id"] == self.active_project_id:
                return project
        return None

    def _brain_index_path(self, project_id: str) -> Path:
        return self.workspace_root / "project-brain" / f"{project_id}.json"

    @staticmethod
    def _import_report_setting_key(project_id: str) -> str:
        return f"import-report:{project_id}"

    def _load_import_report(self, project_id: str) -> dict[str, Any] | None:
        value = self.store.get_setting(self._import_report_setting_key(project_id))
        if not isinstance(value, dict):
            return None
        status = value.get("status")
        copied_files = value.get("copied_files")
        skipped_files = value.get("skipped_files")
        categories = value.get("categories")
        if (
            status not in {"ready", "ready_with_exclusions", "partial"}
            or not isinstance(copied_files, int)
            or copied_files < 0
            or not isinstance(skipped_files, int)
            or skipped_files < 0
            or not isinstance(categories, dict)
        ):
            return None
        normalized_categories: dict[str, int] = {}
        for key, count in categories.items():
            if not isinstance(key, str) or not isinstance(count, int) or count < 0:
                return None
            normalized_categories[key] = count
        if sum(normalized_categories.values()) != skipped_files:
            return None
        return {
            "status": status,
            "copied_files": copied_files,
            "skipped_files": skipped_files,
            "categories": normalized_categories,
        }

    def _refresh_brain_index(self) -> ProjectBrainIndex:
        if self.active_project_id is None or self.detection is None:
            raise RuntimeError("Choose a project first.")
        result = build_load_save_project_brain_index(
            self.detection.descriptor.root,
            self._brain_index_path(self.active_project_id),
        )
        index = result.index
        with self.lock:
            self.brain_index = index
        return index

    def select_project(self, project_id: str, *, restore: bool = False) -> None:
        project = self.store.get_project(project_id)
        detection = self.project_service.detect(project.root)
        import_report = self._load_import_report(project.project_id)
        with self.lock:
            self.active_project_id = project.project_id
            self.active_task_id = None
            self.imported = ImportedProject(
                source=Path(project.root),
                project_root=Path(project.root),
                workspace_root=Path(project.root).parent,
                skipped_members=(),
            )
            self.import_report = import_report
            self.detection = detection
            self.task = None
            self.plan = None
            self.context = None
            self.budget = None
            self.brain_index = None
            self.benchmark = None
            self.graph = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.phase = "task"
            self.message_level = (
                "warning"
                if import_report is not None and import_report["skipped_files"]
                else "success"
                if import_report is not None
                else "info"
            )
            self.error = None
            self.continuation_context = None
            self.message = "پروژه بازیابی شد." if restore else "پروژه انتخاب شد."
        self.store.set_setting("active_project_id", project.project_id)
        if not restore:
            self.store.set_setting("active_task_id", None)
        self._refresh_brain_index()

    def _register_import(self, imported: ImportedProject) -> None:
        detection = self.project_service.detect(imported.project_root)
        saved = self.store.save_project(detection.descriptor)
        vault_root = self.workspace_root / "vaults" / saved.project_id
        if not (vault_root / "vault.json").exists():
            initialize_vault(
                project_root=imported.project_root,
                vault_root=vault_root,
                project_id=saved.project_id,
                project_name=saved.display_name,
            )
        self.select_project(saved.project_id)
        with self.lock:
            self.imported = imported
            self.detection = detection
            skipped = len(imported.skipped_members)
            categories = summarize_import_skips(imported.skipped_members)
            import_report = {
                "status": "ready"
                if not skipped
                else (
                    "partial"
                    if categories.get("access_or_copy", 0)
                    else "ready_with_exclusions"
                ),
                "copied_files": imported.copied_members,
                "skipped_files": skipped,
                "categories": categories,
            }
            self.import_report = import_report
            self.message_level = "success" if not skipped else "warning"
            self.message = (
                (
                    "Project imported into an isolated copy. "
                    f"{imported.copied_members} usable file(s) copied; "
                    f"{skipped} excluded item(s) are explained below."
                    if self.language == "en"
                    else "پروژه در یک کپی ایزوله وارد شد؛ "
                    f"{imported.copied_members} فایل قابل‌استفاده کپی شد و "
                    f"{skipped} مورد کنارگذاشته‌شده در بررسی واردسازی توضیح داده شده است."
                )
                if skipped
                else (
                    "Project saved in an isolated copy."
                    if self.language == "en"
                    else "پروژه در یک کپی ایزوله ذخیره شد."
                )
            )
        self.store.set_setting(
            self._import_report_setting_key(saved.project_id),
            import_report,
        )

    def import_path(self, path: str) -> None:
        selected = Path(path).expanduser().resolve()
        imports_root = self.workspace_root / "imports"
        if selected.is_file() and selected.suffix.lower() == ".zip":
            imported = import_project_archive(selected, imports_root)
        elif selected.is_dir():
            imported = import_project_folder(selected, imports_root)
        else:
            raise ValueError("Choose an existing project folder or a ZIP archive.")
        self._register_import(imported)

    def start_folder_upload(self) -> str:
        upload_id = uuid.uuid4().hex
        root = self.workspace_root / "uploads" / upload_id
        root.mkdir(parents=True, exist_ok=False)
        with self.lock:
            self.upload_sessions[upload_id] = UploadSession(upload_id, root)
        return upload_id

    def _upload_session(self, upload_id: str) -> UploadSession:
        with self.lock:
            session = self.upload_sessions.get(upload_id)
        if session is None:
            raise ValueError("Upload session is missing or expired.")
        return session

    def receive_folder_upload(
        self,
        upload_id: str,
        relative_name: str,
        stream: Any,
        content_length: int,
    ) -> dict[str, Any]:
        session = self._upload_session(upload_id)
        relative = safe_upload_relative_path(relative_name)
        if relative is None:
            with self.lock:
                session.skipped_count += 1
            return {"accepted": False, "skipped": True}
        if content_length < 0 or content_length > MAX_UPLOAD_FILE_BYTES:
            raise ValueError("uploaded file exceeds the per-file size limit")
        if session.total_bytes + content_length > MAX_UPLOAD_TOTAL_BYTES:
            raise ValueError("uploaded project exceeds the total size limit")
        target = session.root / Path(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        remaining = content_length
        try:
            with target.open("wb") as destination:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("uploaded file ended before its declared size")
                    destination.write(chunk)
                    remaining -= len(chunk)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        with self.lock:
            session.total_bytes += content_length
            session.file_count += 1
        return {"accepted": True, "path": relative.as_posix()}

    def finish_folder_upload(self, upload_id: str) -> None:
        session = self._upload_session(upload_id)
        try:
            imported = import_project_folder(session.root, self.workspace_root / "imports")
            if session.skipped_count:
                imported = replace(
                    imported,
                    skipped_members=(*imported.skipped_members, "<browser-upload-skipped>"),
                )
            self._register_import(imported)
        finally:
            with self.lock:
                self.upload_sessions.pop(upload_id, None)
            shutil.rmtree(session.root, ignore_errors=True)

    def cancel_folder_upload(self, upload_id: str) -> None:
        with self.lock:
            session = self.upload_sessions.pop(upload_id, None)
        if session is not None:
            shutil.rmtree(session.root, ignore_errors=True)

    def import_uploaded_zip(
        self,
        filename: str,
        stream: Any,
        content_length: int,
    ) -> None:
        if content_length < 0 or content_length > MAX_UPLOAD_TOTAL_BYTES:
            raise ValueError("uploaded project exceeds the total size limit")
        upload_root = self.workspace_root / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        temporary = upload_root / f"{uuid.uuid4().hex}.zip"
        try:
            remaining = content_length
            with temporary.open("wb") as destination:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("uploaded ZIP ended before its declared size")
                    destination.write(chunk)
                    remaining -= len(chunk)
            imported = import_project_archive(temporary, self.workspace_root / "imports")
            safe_name = Path(filename.replace("\\", "/")).name or "project.zip"
            self._register_import(replace(imported, source=Path(safe_name)))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _task_from_contract(saved: Any) -> ProductTask:
        contract = saved.contract if hasattr(saved, "contract") else None
        raw_task = contract.get("task") if isinstance(contract, dict) else None
        if not isinstance(raw_task, dict):
            raise TypeError("saved task contract is missing its task payload")
        kind_value = str(raw_task["kind"])
        if kind_value not in {"bug_fix", "feature", "ui_improvement", "audit", "release", "custom"}:
            raise ValueError("saved task contract has an unsupported task kind")
        task = ProductTask(
            task_id=str(raw_task["task_id"]),
            project_root=str(raw_task["project_root"]),
            kind=cast(TaskKind, kind_value),
            title=str(raw_task["title"]),
            objective=str(raw_task["objective"]),
            requirements=tuple(str(item) for item in raw_task["requirements"]),
            constraints=tuple(str(item) for item in raw_task["constraints"]),
            definition_of_done=tuple(str(item) for item in raw_task["definition_of_done"]),
            status="ready_for_planning",
        )
        task.validate()
        return task

    def _materialize_workflow(
        self,
        task: ProductTask,
    ) -> tuple[ExecutionPlan, ContextSelection, TokenBudget, AgentRunGraph]:
        if self.detection is None:
            raise RuntimeError("Choose a project first.")
        draft = generate_execution_plan(task=task, project=self.detection)
        plan = approve_execution_plan(draft, current_task=task)
        self._refresh_brain_index()
        context = build_context_selection(
            task=task,
            project=self.detection,
            plan=plan,
            brain_index=self.brain_index,
        )
        budget = lock_token_budget(build_token_budget(plan=plan, selection=context))
        graph = build_agent_run_graph(plan=plan, selection=context, budget=budget)
        return plan, context, budget, graph

    def select_task(self, task_id: str, *, restore: bool = False) -> None:
        if self.active_project_id is None or self.detection is None:
            raise RuntimeError("Choose a project first.")
        saved = self.store.get_task(task_id)
        if saved.project_id != self.active_project_id:
            raise ValueError("task does not belong to the selected project")
        task = self._task_from_contract(saved)
        plan, context, budget, graph = self._materialize_workflow(task)
        releases = self.store.list_task_releases(task.task_id)
        latest_release = releases[0] if releases else None
        restored_export = (
            ExportedProject(
                project_root=self.detection.descriptor.root,
                archive_path=Path(latest_release.archive_path),
                manifest_path=Path(latest_release.manifest_path),
                checksum_path=Path(latest_release.checksum_path),
                sha256=latest_release.sha256,
                file_count=latest_release.file_count,
                verified=latest_release.verified,
            )
            if latest_release is not None
            else None
        )
        with self.lock:
            self.active_task_id = task.task_id
            self.task = task
            self.plan = plan
            self.context = context
            self.budget = budget
            self.benchmark = None
            self.graph = graph
            self.run = None
            self.verification = None
            self.review = None
            self.export = restored_export
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = None
            self.message = "تیکت قبلی بازیابی شد." if restore else "تیکت انتخاب شد."
        self.store.set_setting("active_task_id", task.task_id)
        self._restore_task_artifacts(task.task_id)

    def _run_manifest_path(self, workspace_run_id: str) -> Path:
        return self.workspace_root / "run-manifests" / f"{workspace_run_id}.json"

    def _write_run_manifest(
        self,
        workspace_run_id: str,
        *,
        codex_run_id: str,
        verification_id: str | None = None,
        review_id: str | None = None,
    ) -> Path:
        destination = self._run_manifest_path(workspace_run_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema_version": 1,
            "workspace_run_id": workspace_run_id,
            "codex_run_id": codex_run_id,
            "verification_id": verification_id,
            "review_id": review_id,
        }
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def _restore_task_artifacts(self, task_id: str) -> None:
        runs = self.store.list_task_runs(task_id)
        if not runs:
            return
        latest = runs[0]
        manifest_path = (
            Path(latest.evidence_path)
            if latest.evidence_path
            else None
        )
        if manifest_path is None or not manifest_path.is_file():
            return
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError("run manifest must be an object")
            codex_run_id = str(value["codex_run_id"])
            restored_run = self.execution_store.get_run(codex_run_id)
            if restored_run is None:
                return
            restored_verification = None
            verification_id = value.get("verification_id")
            if verification_id:
                restored_verification = self.verification_store.load(str(verification_id))
            restored_review = None
            review_id = value.get("review_id")
            if review_id:
                restored_review = self.review_store.load(str(review_id))
        except (OSError, KeyError, TypeError, ValueError):
            return
        stale_reason: str | None = None
        if restored_verification is not None and self.detection is not None:
            try:
                stale_reason = verification_staleness_reason(
                    restored_verification,
                    self.detection,
                )
                current_signature = verification_contract_signature(self.detection)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                stale_reason = (
                    "Stored verification evidence could not be reconciled with "
                    f"the current project checks: {exc}"
                )
                current_signature = None
            if stale_reason is not None:
                restored_verification = replace(
                    restored_verification,
                    status="fail",
                    finalized_at=None,
                    diagnostics=tuple(
                        dict.fromkeys(
                            (*restored_verification.diagnostics, stale_reason)
                        )
                    ),
                    contract_signature=current_signature,
                )
                self.verification_store.save(restored_verification)
                if restored_run.status == "completed":
                    restored_run = replace(
                        restored_run,
                        status="failed",
                        error_code="process_failed",
                        error_message=stale_reason,
                    )
        with self.lock:
            self.run = restored_run
            self.verification = restored_verification
            self.review = restored_review
            self.node_states = {
                item.node_id: item.status for item in restored_run.node_results
            }
            if self.export is None:
                self.phase = "result" if restored_review is not None else "run"
            self.message = (
                "نتیجه‌ی قبلی بازیابی شد؛ برای ادامه باید Verification دوباره اجرا شود."
                if stale_reason is not None
                else "نتیجهٔ تیکت بازیابی شد."
            )

    def _build_continuation_context(self) -> str:
        roots = (
            self.detection.descriptor.root if self.detection is not None else self.workspace_root,
            self.workspace_root,
        )
        if self.verification is not None:
            lines = [
                "Previous Empy verification findings from the last attempt must be addressed before release:",
            ]
            lines.extend(f"- {item}" for item in self.verification.diagnostics)
            for result in self.verification.results:
                if result.status != "fail":
                    continue
                output = result.stderr.strip() or result.stdout.strip()
                detail = _safe_verification_detail(output, roots)
                lines.append(
                    f"- {result.check.label} (return code {result.returncode}): {detail}"
                )
            return "\n".join(lines)[:4000]
        message = self.run.error_message if self.run is not None else self.error
        if message:
            return (
                "Previous Empy execution failed and the next attempt must diagnose and resolve it before release:\n"
                f"- {_safe_verification_detail(message, roots)}"
            )[:4000]
        return "Previous Empy execution did not produce a complete result. Re-check the requested work and the project verification path before release."

    def resume_ticket(self) -> None:
        if self.detection is None or self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        if self.running:
            raise RuntimeError("Stop the active run before continuing the ticket.")
        context = self._build_continuation_context()
        with self.lock:
            self.continuation_context = context
            self.active_task_id = None
            self.task = None
            self.plan = None
            self.context = None
            self.budget = None
            self.benchmark = None
            self.graph = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.node_states.clear()
            self.phase = "task"
            self.error = None
            self.message = "یافته‌های شکست قبلی حفظ شد؛ تیکت اصلاحی را وارد کنید."
        self.store.set_setting("active_task_id", None)

    def create_plan(self, raw_tasks: str, task_id: str | None = None) -> None:
        if self.detection is None or self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        raw = raw_tasks.strip()
        if not raw:
            raise ValueError("Enter at least one task.")
        requirements, user_constraints = _split_task_lines(raw)
        if not requirements:
            raise ValueError("Enter at least one actionable task.")
        continuation_context = self.continuation_context
        objective_requirements = list(requirements)
        if continuation_context:
            objective_requirements.append(continuation_context)
        task = build_product_task(
            task_id=task_id or uuid.uuid4().hex,
            project_root=str(self.detection.descriptor.root),
            kind="custom",
            title=requirements[0][:96],
            objective="\n".join(objective_requirements),
            requirements_text="\n".join(objective_requirements),
            constraints_text="\n".join((DEFAULT_CONSTRAINTS, *user_constraints)),
            definition_of_done_text=DEFAULT_DEFINITION_OF_DONE,
        )
        ready = mark_ready_for_planning(task)
        plan, context, budget, graph = self._materialize_workflow(ready)
        contract = {
            "task": asdict(ready),
            "plan": plan.to_dict(),
            "context": context.to_dict(),
            "budget": budget.to_dict(),
            "graph": graph.to_dict(),
        }
        if task_id is None:
            self.store.create_task(
                project_id=self.active_project_id,
                title=ready.title,
                request_text=raw,
                task_kind=ready.kind,
                contract=contract,
                status="planned",
                task_id=ready.task_id,
            )
        else:
            self.store.update_task(
                task_id,
                title=ready.title,
                request_text=raw,
                task_kind=ready.kind,
                contract=contract,
                status="planned",
            )
        with self.lock:
            self.active_task_id = ready.task_id
            self.task = ready
            self.plan = plan
            self.context = context
            self.budget = budget
            self.benchmark = None
            self.graph = graph
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = None
            self.continuation_context = None
            self.message = "برنامه و مالکیت فایل‌ها آماده شد."
        self.store.set_setting("active_task_id", ready.task_id)

    def run_benchmark(self) -> BenchmarkResult:
        if self.task is None or self.detection is None or self.plan is None:
            raise RuntimeError("Build a plan before running the benchmark.")
        index = self._refresh_brain_index()
        result = run_local_benchmark(
            task=self.task,
            project=self.detection,
            plan=self.plan,
            brain_index=index,
            selection=self.context,
            budget=self.budget,
        )
        with self.lock:
            self.benchmark = result
            self.message = "بنچمارک محلی بدون فراخوانی Provider اجرا شد."
        return result

    def start_run(self) -> None:
        if self.running:
            raise RuntimeError("A run is already active.")
        if self.graph is None or self.context is None or self.budget is None or self.detection is None:
            raise RuntimeError("Build a plan first.")
        installation = self.driver.inspect(refresh=True)
        if installation.availability != "available" or not installation.authenticated:
            raise RuntimeError(installation.remediation or installation.message)
        if self.active_project_id is None or self.active_task_id is None:
            raise RuntimeError("Project and task identity are missing.")
        run = self.store.create_run(
            task_id=self.active_task_id,
            project_id=self.active_project_id,
            summary="Codex run started",
            state="running",
            driver_name="codex",
        )
        runtime = CodexGraphRuntime(
            driver=self.driver,
            run_root=self.workspace_root / "codex-runs",
        )
        cancel_event = threading.Event()
        with self.lock:
            self.running = True
            self.runtime = runtime
            self.cancel_event = cancel_event
            self.phase = "run"
            self.error = None
            self.message = "اجرای Agentها شروع شد."
            self.logs.clear()
        thread = threading.Thread(target=self._run_worker, args=(run.run_id,), daemon=True, name="empy-web-run")
        thread.start()

    def cancel_run(self) -> None:
        with self.lock:
            if not self.running or self.runtime is None:
                raise RuntimeError("There is no active run to cancel.")
            runtime = self.runtime
            cancel_event = self.cancel_event
            self.message = "درخواست توقف اجرا ثبت شد."
        if cancel_event is not None:
            cancel_event.set()
        runtime.cancel()
        self.add_log("Run cancellation requested.", "warning")

    def _save_runtime_result(
        self,
        workspace_run_id: str,
        result: CodexGraphExecution,
        *,
        verification_id: str | None = None,
        review_id: str | None = None,
    ) -> Path:
        self.execution_store.save_run(result)
        return self._write_run_manifest(
            workspace_run_id,
            codex_run_id=result.run_id,
            verification_id=verification_id,
            review_id=review_id,
        )

    def _record_terminal_result(
        self,
        workspace_run_id: str,
        result: CodexGraphExecution,
        *,
        state: str,
        message: str,
        level: str,
        verification_id: str | None = None,
        review_id: str | None = None,
    ) -> None:
        self.run = result
        manifest_path = self._save_runtime_result(
            workspace_run_id,
            result,
            verification_id=verification_id,
            review_id=review_id,
        )
        self.store.update_run(
            workspace_run_id,
            state=state,
            summary=message,
            driver_name="codex",
            evidence_path=str(manifest_path),
        )
        with self.lock:
            self.running = False
            self.runtime = None
            self.cancel_event = None
            self.phase = "run" if state != "completed" else "result"
            self.error = message if state != "completed" else None
            self.message = (
                "اجرا لغو شد."
                if state == "cancelled"
                else "اجرا با خطا متوقف شد."
                if state == "failed"
                else "نتیجه برای Review آماده است."
            )
        self.add_log(message, level)

    def _run_worker(self, workspace_run_id: str) -> None:
        graph = self.graph
        context = self.context
        budget = self.budget
        detection = self.detection
        task = self.task
        result: CodexGraphExecution | None = None
        if (
            graph is None
            or context is None
            or budget is None
            or detection is None
            or task is None
        ):
            self._record_failure(workspace_run_id, "Run inputs are incomplete.")
            return

        def progress(event: CodexProgressEvent) -> None:
            if event.node_id:
                with self.lock:
                    self.node_states[event.node_id] = "failed" if event.level == "error" else "running"
            self.add_log(event.message, event.level)

        try:
            with self.lock:
                runtime = self.runtime
            if runtime is None:
                raise RuntimeError("The run runtime was not initialized.")
            result = runtime.run(
                graph=graph,
                selection=context,
                budget=budget,
                project=detection.descriptor,
                task=task,
                on_progress=progress,
            )
            self.run = result
            for node in result.node_results:
                self.node_states[node.node_id] = node.status
            if result.status != "completed":
                terminal_message = result.error_message or f"Codex run ended as {result.status}"
                terminal_state = "cancelled" if result.status == "cancelled" else "failed"
                self._record_terminal_result(
                    workspace_run_id,
                    result,
                    state=terminal_state,
                    message=terminal_message,
                    level="warning" if result.status == "cancelled" else "error",
                )
                return
            cancel_event = self.cancel_event
            if cancel_event is not None and cancel_event.is_set():
                raise VerificationCancelled("Verification was cancelled before it started.")
            verification = VerificationRuntime().run(
                detection=detection,
                evidence_root=self.verification_store.evidence_root,
                on_event=self._verification_event,
                cancel_event=cancel_event,
            )
            if cancel_event is not None and cancel_event.is_set():
                raise VerificationCancelled("Verification was cancelled.")
            if verification.finalize_allowed:
                verification = finalize_verification(verification)
            review = self.review_store.create(detection.descriptor.root)
            self.verification = verification
            self.review = review
            self.verification_store.save(verification)
            final_result = (
                result
                if verification.finalize_allowed
                else replace(
                    result,
                    status="failed",
                    error_code="process_failed",
                    error_message="Verification failed; review is required before export.",
                )
            )
            self.run = final_result
            manifest_path = self._save_runtime_result(
                workspace_run_id,
                final_result,
                verification_id=verification.verification_id,
                review_id=review.review_id,
            )
            self.store.update_run(
                workspace_run_id,
                state="completed" if verification.finalize_allowed else "failed",
                summary="Run and verification completed" if verification.finalize_allowed else "Verification failed",
                driver_name="codex",
                evidence_path=str(manifest_path),
            )
            if self.active_task_id is not None:
                self.store.update_task(self.active_task_id, status="review")
            with self.lock:
                self.running = False
                self.runtime = None
                self.cancel_event = None
                self.phase = "result"
                self.message = (
                    "نتیجه برای Review آماده است."
                    if verification.finalize_allowed
                    else "Verification ناموفق بود؛ یافته‌ها را اصلاح و تیکت را ادامه دهید."
                )
                self.error = (
                    None
                    if verification.finalize_allowed
                    else "Verification failed; review the findings and continue the ticket."
                )
        except VerificationCancelled as exc:
            cancelled = (
                replace(
                    result,
                    status="cancelled",
                    error_code="cancelled",
                    error_message=str(exc),
                )
                if result is not None
                else None
            )
            if cancelled is None:
                self._record_failure(workspace_run_id, str(exc), state="cancelled")
            else:
                self._record_terminal_result(
                    workspace_run_id,
                    cancelled,
                    state="cancelled",
                    message=str(exc),
                    level="warning",
                )
        except VerificationTimedOut as exc:
            failed = (
                replace(
                    result,
                    status="failed",
                    error_code="timeout",
                    error_message=str(exc),
                )
                if result is not None
                else None
            )
            if failed is None:
                self._record_failure(workspace_run_id, str(exc))
            else:
                self._record_terminal_result(
                    workspace_run_id,
                    failed,
                    state="failed",
                    message=str(exc),
                    level="error",
                )
        except (OSError, RuntimeError, ValueError) as exc:
            if result is not None and result.status == "completed":
                failed = replace(
                    result,
                    status="failed",
                    error_code="process_failed",
                    error_message=str(exc),
                )
                self._record_terminal_result(
                    workspace_run_id,
                    failed,
                    state="failed",
                    message=str(exc),
                    level="error",
                )
            else:
                self._record_failure(workspace_run_id, str(exc))

    def _record_failure(
        self,
        workspace_run_id: str,
        message: str,
        *,
        state: str = "failed",
    ) -> None:
        try:
            self.store.update_run(workspace_run_id, state=state, summary=message, driver_name="codex")
        except KeyError:
            pass
        with self.lock:
            self.running = False
            self.runtime = None
            self.cancel_event = None
            self.phase = "run"
            self.error = message
            self.message = "اجرا لغو شد." if state == "cancelled" else "اجرا متوقف شد."
        self.add_log(message, "warning" if state == "cancelled" else "error")

    def _verification_event(self, event: VerificationEvent) -> None:
        if event.text.strip():
            self.add_log(event.text, "error" if event.stream == "stderr" else "info")

    def decide_all(self, decision: str) -> None:
        if self.review is None:
            raise RuntimeError("Review is not ready.")
        if decision not in {"accept", "revert"}:
            raise ValueError("decision must be accept or revert")
        report = self.review
        for item in tuple(report.files):
            if item.decision != "pending":
                continue
            report = (
                self.review_store.accept(report.review_id, item.relative_path)
                if decision == "accept"
                else self.review_store.revert(report.review_id, item.relative_path)
            )
        if decision == "accept":
            checkpoint_accepted_changes(
                report.project_root,
                (
                    item.relative_path
                    for item in report.files
                    if item.decision == "accepted"
                ),
            )
        self.review = report
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="accepted" if decision == "accept" else "reverted")
        self.message = "تصمیم روی تغییرات ثبت شد."

    def _release_gate(self) -> dict[str, Any]:
        """Return the evidence-backed conditions for creating a project ZIP."""

        blockers: list[str] = []
        if self.run is not None and self.run.status != "completed":
            blockers.append("The agent run did not complete successfully.")
        if self.verification is None:
            blockers.append("Verification has not run.")
        elif (
            self.verification.status != "pass"
            or self.verification.finalized_at is None
            or not self.verification.finalize_allowed
        ):
            blockers.extend(self.verification.diagnostics)
            if not blockers:
                blockers.append("Verification has not passed and been finalized.")

        if self.review is None:
            blockers.append("Review has not been created.")
        elif self.review.pending_count:
            blockers.append(
                f"{self.review.pending_count} changed file(s) still need a review decision."
            )
        elif self.review.status != "complete":
            blockers.append("Review has not completed.")

        if self.export is not None and self.export.verified:
            status = "exported"
        elif blockers:
            status = "blocked"
        else:
            status = "ready_for_export"
        return {
            "status": status,
            "ready": not blockers,
            "blockers": blockers,
            "exported": bool(self.export and self.export.verified),
        }

    def export_project(self, destination: str | None = None) -> None:
        gate = self._release_gate()
        if not gate["ready"]:
            detail = "; ".join(str(item) for item in gate["blockers"])
            raise RuntimeError(f"Export is blocked: {detail}")
        if self.detection is None or self.review is None:
            raise RuntimeError("There is no reviewed project to export.")
        target = Path(destination).expanduser() if destination else (
            self.workspace_root / "releases" / f"{self.detection.descriptor.display_name}-{uuid.uuid4().hex[:8]}.zip"
        )
        exported = export_project_zip(self.detection.descriptor.root, target)
        self.export = exported
        if self.active_project_id is not None and self.active_task_id is not None:
            self.store.create_release(
                task_id=self.active_task_id,
                project_id=self.active_project_id,
                archive_path=str(exported.archive_path),
                manifest_path=str(exported.manifest_path),
                checksum_path=str(exported.checksum_path),
                sha256=exported.sha256,
                file_count=exported.file_count,
                verified=exported.verified,
            )
        self.message = "فایل ZIP تک‌ریشه و قابل استخراج آماده شد."
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="released")

    def reset(self) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("Stop the active run before switching projects.")
            self.active_project_id = None
            self.active_task_id = None
            self.imported = None
            self.detection = None
            self.task = None
            self.plan = None
            self.context = None
            self.budget = None
            self.brain_index = None
            self.benchmark = None
            self.graph = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.import_report = None
            self.runtime = None
            self.cancel_event = None
            self.phase = "project"
            self.message_level = "info"
            self.error = None
            self.continuation_context = None
            self.message = ""
            self.logs.clear()
        self.store.set_setting("active_project_id", None)
        self.store.set_setting("active_task_id", None)

    def public(self) -> dict[str, Any]:
        with self.lock:
            inspection = self.driver.inspect(refresh=False)
            project = self._active_project()
            tasks = project["tasks"] if project else []
            plan = None
            if self.graph is not None and self.context is not None and self.budget is not None:
                plan = {
                    "agents": len({node.agent_id for node in self.graph.nodes}),
                    "steps": len(self.graph.nodes),
                    "roles": list(dict.fromkeys(node.agent_role for node in self.graph.nodes)),
                    "nodes": [
                        {
                            "id": node.node_id,
                            "role": node.agent_role,
                            "title": node.title,
                            "owned_files": list(node.owned_files),
                            "read_only_files": list(node.read_only_files),
                            "status": self.node_states.get(node.node_id, "waiting"),
                        }
                        for node in self.graph.nodes
                    ],
                    "selected_files": self.context.selected_files,
                    "scanned_files": self.context.scanned_candidates,
                    "token_limit": self.budget.total_limit_tokens,
                    "estimated_context_tokens": self.budget.estimated_context_tokens,
                    "estimate_source": "provider_neutral_local_estimate",
                }
            budget = (
                {
                    "status": self.budget.status,
                    "preset": self.budget.preset,
                    "planning_limit_tokens": self.budget.planning_limit_tokens,
                    "reserve_tokens": self.budget.reserve_tokens,
                    "total_limit_tokens": self.budget.total_limit_tokens,
                    "estimated_context_tokens": self.budget.estimated_context_tokens,
                    "source": "provider_neutral_local_estimate",
                }
                if self.budget is not None
                else None
            )
            provider_usage = self._provider_usage()
            review = self.review.to_dict() if self.review is not None else None
            verification = self.verification.to_dict() if self.verification is not None else None
            return cast(dict[str, Any], _json_safe(
                {
                    "language": self.language,
                    "phase": "saved" if self.export else self.phase,
                    "message": self.message,
                    "message_level": self.message_level,
                    "error": self.error,
                    "projects": self._project_records(),
                    "active_project": project,
                    "active_task_id": self.active_task_id,
                    "tasks": tasks,
                    "task": asdict(self.task) if self.task is not None else None,
                    "plan": plan,
                    "brain": self.brain_index.stats() if self.brain_index is not None else None,
                    "budget": budget,
                    "provider_usage": provider_usage,
                    "estimate_source": "provider_neutral_local_estimate",
                    "benchmark": self.benchmark.to_dict() if self.benchmark is not None else None,
                    "run_status": self.run.status if self.run is not None else None,
                    "run_error": self.run.error_message if self.run is not None else None,
                    "run_report": self._execution_report(),
                    "running": self.running,
                    "logs": list(self.logs),
                    "verification": verification,
                    "review": review,
                    "export": self.export.to_dict() if self.export is not None else None,
                    "import_report": self.import_report,
                    "release_gate": self._release_gate(),
                    "engine": {
                        "provider": inspection.display_name,
                        "availability": inspection.availability,
                        "ready": inspection.availability == "available" and inspection.authenticated,
                        "version": inspection.version,
                        "message": inspection.message,
                        "remediation": inspection.remediation,
                    },
                }
            ))

    def _provider_usage(self) -> dict[str, Any] | None:
        if self.run is None:
            return None
        usage = self.run.usage
        if usage is not None and not isinstance(usage, TokenUsage):
            raise TypeError("Codex run usage must be a TokenUsage record")
        return _usage_summary(
            usage,
            provider=self.run.provider,
            status=self.run.status,
        )

    def _workspace_reference(self, value: str) -> str:
        """Expose evidence locations without leaking absolute host paths."""
        try:
            candidate = Path(value).expanduser().resolve()
            return candidate.relative_to(self.workspace_root).as_posix()
        except (OSError, ValueError):
            return Path(value).name or "evidence"

    def _user_guidance(
        self,
        *,
        diagnostics: list[str],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Turn internal run state into the next action a user can take."""

        stale = any(
            "older or different verification contract" in item.casefold()
            for item in diagnostics
        )
        if stale:
            if self.language == "en":
                return {
                    "kind": "stale_verification",
                    "title": "This result needs a fresh verification",
                    "summary": (
                        "Empy cannot safely use the saved verification after its "
                        "rules changed. No ZIP will be created from this result."
                    ),
                    "steps": [
                        "Choose Continue and fix ticket to start a new verification.",
                        "Review the new result; the ZIP becomes available only after Verification passes.",
                    ],
                    "action": "resume-ticket",
                }
            return {
                "kind": "stale_verification",
                "title": "این نتیجه به بررسی تازه نیاز دارد",
                "summary": (
                    "قواعد بررسی Empy تغییر کرده است؛ نتیجه‌ی ذخیره‌شده دیگر برای ساخت ZIP معتبر نیست."
                ),
                "steps": [
                    "روی «ادامه و اصلاح تیکت» بزنید تا بررسی تازه شروع شود.",
                    "نتیجه‌ی جدید را مرور کنید؛ ZIP فقط بعد از موفق شدن Verification فعال می‌شود.",
                ],
                "action": "resume-ticket",
            }

        if failures:
            if self.language == "en":
                return {
                    "kind": "verification_failed",
                    "title": "A project check did not pass",
                    "summary": (
                        "Empy found a problem in the project checks, so it has blocked the ZIP."
                    ),
                    "steps": [
                        "Open the optional technical details only if you need the exact check output.",
                        "Choose Continue and fix ticket so Empy can prepare a correction in the isolated copy.",
                        "Run Verification again after the correction; the ZIP will unlock only after it passes.",
                    ],
                    "action": "resume-ticket",
                }
            return {
                "kind": "verification_failed",
                "title": "یک بررسی پروژه موفق نشد",
                "summary": "Empy در بررسی پروژه مشکل پیدا کرد؛ برای جلوگیری از ZIP ناقص، خروجی مسدود شد.",
                "steps": [
                    "جزئیات فنی فقط در صورت نیاز، داخل بخش «جزئیات فنی (اختیاری)» قرار دارد.",
                    "روی «ادامه و اصلاح تیکت» بزنید تا Empy اصلاح را در کپی ایزوله‌ی پروژه آماده کند.",
                    "بعد از اصلاح، Verification دوباره اجرا می‌شود و فقط در صورت موفقیت ZIP فعال خواهد شد.",
                ],
                "action": "resume-ticket",
            }

        if self.run is not None and self.run.status != "completed":
            if self.language == "en":
                return {
                    "kind": "run_failed",
                    "title": "The Agent run did not finish",
                    "summary": "The result is not safe to deliver because the Agent run did not complete.",
                    "steps": [
                        "Choose Continue and fix ticket to retry the work in the isolated copy.",
                        "Review the result and Verification before creating a ZIP.",
                    ],
                    "action": "resume-ticket",
                }
            return {
                "kind": "run_failed",
                "title": "اجرای Agentها کامل نشد",
                "summary": "چون اجرای Agentها کامل نشده است، نتیجه برای تحویل امن نیست.",
                "steps": [
                    "برای تلاش دوباره روی «ادامه و اصلاح تیکت» بزنید.",
                    "قبل از ساخت ZIP، نتیجه و Verification را مرور کنید.",
                ],
                "action": "resume-ticket",
            }

        if self.verification is None:
            if self.language == "en":
                return {
                    "kind": "verification_missing",
                    "title": "Final project verification has not run",
                    "summary": "Empy needs a completed Verification before it can create a ZIP.",
                    "steps": ["Choose Continue and fix ticket to continue the workflow."],
                    "action": "resume-ticket",
                }
            return {
                "kind": "verification_missing",
                "title": "بررسی نهایی پروژه هنوز اجرا نشده است",
                "summary": "Empy قبل از ساخت ZIP باید Verification کامل داشته باشد.",
                "steps": ["برای ادامه‌ی مسیر روی «ادامه و اصلاح تیکت» بزنید."],
                "action": "resume-ticket",
            }

        return None

    def _execution_report(self) -> dict[str, Any] | None:
        if self.run is None:
            return None

        graph_nodes = {node.node_id: node for node in self.graph.nodes} if self.graph else {}
        results = {node.node_id: node for node in self.run.node_results}
        node_reports: list[dict[str, Any]] = []
        for node_id, graph_node in graph_nodes.items():
            result = results.get(node_id)
            status = result.status if result is not None else self.node_states.get(node_id, "waiting")
            estimated_tokens = graph_node.token_limit
            usage = result.usage if result is not None else None
            if usage is not None and not isinstance(usage, TokenUsage):
                raise TypeError("Codex node usage must be a TokenUsage record")
            evidence = None
            if result is not None:
                evidence = {
                    "events": self._workspace_reference(result.events_path),
                    "stderr": self._workspace_reference(result.stderr_path),
                    "final_message": self._workspace_reference(result.final_message_path),
                    "command": self._workspace_reference(result.command_path),
                }
            node_reports.append(
                {
                    "id": node_id,
                    "agent_id": graph_node.agent_id,
                    "role": graph_node.agent_role,
                    "title": graph_node.title,
                    "status": status,
                    "wave": graph_node.wave,
                    "duration_seconds": (
                        _duration_seconds(result.started_at, result.finished_at)
                        if result is not None
                        else None
                    ),
                    "summary": result.summary if result is not None else graph_node.objective,
                    "error": result.error_message if result is not None else None,
                    "changed_files": list(result.changed_files) if result is not None else [],
                    "event_count": result.event_count if result is not None else 0,
                    "token_limit": estimated_tokens,
                    "usage": _usage_summary(
                        usage,
                        provider=self.run.provider,
                        status=status,
                        estimated_tokens=estimated_tokens,
                    ),
                    "evidence": evidence,
                }
            )

        verification_results = self.verification.results if self.verification is not None else ()
        passed_checks = sum(item.status == "pass" for item in verification_results)
        failed_checks = sum(item.status != "pass" for item in verification_results)
        verification_diagnostics = list(self.verification.diagnostics) if self.verification is not None else []
        verification_failures = [
            {
                "check_id": item.check.check_id,
                "label": item.check.label,
                "category": item.check.category,
                "returncode": item.returncode,
                "detail": _safe_verification_detail(
                    item.stderr or item.stdout,
                    (
                        self.detection.descriptor.root if self.detection is not None else self.workspace_root,
                        self.workspace_root,
                    ),
                ),
            }
            for item in verification_results
            if item.status == "fail"
        ]
        guidance = self._user_guidance(
            diagnostics=verification_diagnostics,
            failures=verification_failures,
        )
        review_files = self.review.files if self.review is not None else ()
        benchmark = self.benchmark
        estimates = {
            "bounded_context_tokens": (
                benchmark.bounded_context_estimate_tokens
                if benchmark is not None
                else self.budget.estimated_context_tokens if self.budget is not None else None
            ),
            "full_context_tokens": benchmark.full_context_estimate_tokens if benchmark is not None else None,
            "saved_tokens": benchmark.saved_tokens if benchmark is not None else None,
            "savings_percentage": benchmark.savings_percentage if benchmark is not None else None,
            "source": "provider_neutral_local_estimate",
        }
        return {
            "run_id": self.run.run_id,
            "provider": self.run.provider,
            "status": self.run.status,
            "started_at": self.run.started_at,
            "finished_at": self.run.finished_at,
            "duration_seconds": _duration_seconds(self.run.started_at, self.run.finished_at),
            "summary": self.run.error_message or (
                "Run completed" if self.run.status == "completed" else "Run ended"
            ),
            "error": self.run.error_message,
            "nodes": node_reports,
            "schedule": [item.to_dict() for item in self.run.schedule],
            "usage": self._provider_usage(),
            "estimates": estimates,
            "verification": {
                "status": self.verification.status if self.verification is not None else "not_run",
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "total_checks": len(verification_results),
                "finalized": bool(self.verification and self.verification.finalized_at),
                "diagnostics": verification_diagnostics,
                "failures": verification_failures,
            },
            "guidance": guidance,
            "review": {
                "changed_files": len(review_files),
                "pending": self.review.pending_count if self.review is not None else 0,
                "accepted": self.review.accepted_count if self.review is not None else 0,
                "reverted": self.review.reverted_count if self.review is not None else 0,
                "ready": self.review is not None and self.review.pending_count == 0,
            },
            "export": {
                **self._release_gate(),
                "available": self.export is not None,
                "verified": bool(self.export and self.export.verified),
                "file_count": self.export.file_count if self.export is not None else None,
                "guidance": guidance,
            },
        }


def _native_picker(kind: str) -> str | None:
    if sys.platform != "darwin":
        return None
    if kind == "folder":
        script = 'POSIX path of (choose folder with prompt "Choose project folder")'
    else:
        script = 'POSIX path of (choose file with prompt "Choose project ZIP" of type {"zip"})'
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _open_external(target: str | Path, *, reveal: bool = False) -> bool:
    """Open a URL or reveal a file using the host platform's default handler."""
    if reveal:
        path = Path(target).expanduser()
        if sys.platform == "darwin" and shutil.which("open"):
            return subprocess.run(
                [shutil.which("open") or "open", "-R", str(path)],
                check=False,
            ).returncode == 0
        if os.name == "nt":
            try:
                os.startfile(str(path.parent))  # type: ignore[attr-defined]
                return True
            except OSError:
                return False
        opener = shutil.which("xdg-open")
        if opener:
            return subprocess.run([opener, str(path.parent)], check=False).returncode == 0
        return False
    try:
        return bool(webbrowser.open(str(target)))
    except OSError:
        return False


class AppServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: GuidedState, token: str) -> None:
        super().__init__(address, RequestHandler)
        self.state = state
        self.token = token
        self.web_root = WEB_ROOT.resolve()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "EmpyStudioWeb/1.0"

    @property
    def app(self) -> AppServer:
        return cast(AppServer, self.server)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _authorized(self) -> bool:
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        return query_token == self.app.token or self.headers.get("X-Empy-Token") == self.app.token

    def _send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(_json_safe(value), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _content_length(self) -> int:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("request body length is invalid") from exc
        if length < 0:
            raise ValueError("request body length is invalid")
        return length

    def _read_json(self) -> dict[str, Any]:
        length = self._content_length()
        if length > 1024 * 1024:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("request body must be an object")
        return value

    def _send_static(self, target: Path, content_type: str) -> None:
        body = target.read_bytes()
        self.send_response(200)
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type = f"{content_type}; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_static(self.app.web_root / "index.html", "text/html")
            return
        if parsed.path.startswith("/assets/"):
            target = (self.app.web_root / parsed.path.removeprefix("/assets/")).resolve()
            if self.app.web_root not in target.parents or not target.is_file():
                self.send_error(404)
                return
            self._send_static(target, _content_type_for_asset(target))
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 403)
            return
        if parsed.path in {"/api/state", "/api/health"}:
            self._send_json(self.app.state.public() if parsed.path.endswith("state") else {"ok": True})
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 403)
            return
        try:
            path = urlparse(self.path).path
            if path == "/api/upload-folder/file":
                result = self._handle_folder_upload_file()
            elif path == "/api/upload-zip":
                result = self._handle_zip_upload()
            else:
                body = self._read_json()
                result = self._handle_post(path, body)
            self._send_json(result)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            message = safe_user_error(exc, language=self.app.state.language)
            self.app.state.error = message
            self._send_json({"error": message, "state": self.app.state.public()}, 400)

    def _handle_folder_upload_file(self) -> dict[str, Any]:
        upload_id = self.headers.get("X-Empy-Upload-Id", "")
        relative_path = unquote(self.headers.get("X-Empy-Relative-Path", ""))
        result = self.app.state.receive_folder_upload(
            upload_id,
            relative_path,
            self.rfile,
            self._content_length(),
        )
        return result

    def _handle_zip_upload(self) -> dict[str, Any]:
        self.app.state.import_uploaded_zip(
            unquote(self.headers.get("X-Empy-Filename", "project.zip")),
            self.rfile,
            self._content_length(),
        )
        return self.app.state.public()

    def _handle_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        state = self.app.state
        if path == "/api/import":
            state.import_path(str(body.get("path", "")))
        elif path == "/api/upload-folder/start":
            return {"upload_id": state.start_folder_upload(), "state": state.public()}
        elif path == "/api/upload-folder/finish":
            state.finish_folder_upload(str(body.get("upload_id", "")))
        elif path == "/api/upload-folder/cancel":
            state.cancel_folder_upload(str(body.get("upload_id", "")))
        elif path == "/api/select-folder" or path == "/api/select-zip":
            selected = _native_picker("folder" if path.endswith("folder") else "zip")
            if selected is None:
                return {"cancelled": True, "state": state.public()}
            state.import_path(selected)
        elif path == "/api/project/select":
            state.select_project(str(body["project_id"]))
        elif path == "/api/task/select":
            state.select_task(str(body["task_id"]))
        elif path == "/api/plan":
            state.create_plan(str(body.get("tasks", "")), body.get("task_id"))
        elif path == "/api/benchmark":
            state.run_benchmark()
        elif path == "/api/run":
            state.start_run()
        elif path == "/api/cancel":
            state.cancel_run()
        elif path == "/api/resume-ticket":
            state.resume_ticket()
        elif path == "/api/decision":
            state.decide_all(str(body.get("decision", "")))
        elif path == "/api/export":
            destination = body.get("destination")
            state.export_project(str(destination) if destination else None)
        elif path == "/api/reset":
            state.reset()
        elif path == "/api/language":
            language = str(body.get("language", "fa"))
            if language not in {"fa", "en"}:
                raise ValueError("language must be fa or en")
            state.language = language
            state.store.set_setting("language", language)
        elif path == "/api/refresh-engine":
            state.driver.inspect(refresh=True)
        elif path == "/api/open-engine":
            _open_external("codex://threads/new")
        elif path == "/api/reveal-export":
            if state.export is not None:
                _open_external(state.export.archive_path, reveal=True)
        else:
            raise ValueError("not found")
        return state.public()


def create_server(
    *,
    workspace: str | Path,
    token: str | None = None,
    port: int = 0,
) -> AppServer:
    state = GuidedState(Path(workspace))
    return AppServer(("127.0.0.1", port), state, token or secrets.token_urlsafe(24))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Empy Studio bilingual guided desktop UI")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=None)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    workspace = args.workspace or default_workspace_root()
    server = create_server(workspace=workspace, token=args.token, port=args.port)
    address = cast(tuple[str, int], server.server_address)
    host, actual_port = address
    url = f"http://{host}:{actual_port}/?token={server.token}"
    print(url, flush=True)
    if not args.no_open:
        _open_external(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
