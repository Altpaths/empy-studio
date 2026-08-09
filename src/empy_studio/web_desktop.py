from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from empy_studio.core import (
    AgentRunGraph,
    ContextSelection,
    DefaultProjectService,
    ExecutionPlan,
    ProductTask,
    ProjectDetection,
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
from empy_studio.drivers import (
    CodexDriver,
    CodexGraphExecution,
    CodexGraphRuntime,
    CodexProgressEvent,
)
from empy_studio.project_delivery import (
    ExportedProject,
    ImportedProject,
    export_project_zip,
    import_project_archive,
    import_project_folder,
)
from empy_studio.review_workspace import ReviewReport, ReviewWorkspaceAdapter
from empy_studio.vault import initialize_vault
from empy_studio.verification_pipeline import (
    VerificationEvent,
    VerificationReport,
    VerificationRuntime,
    finalize_verification,
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


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
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
        line = raw_line.strip(" -•\t")
        if not line:
            continue
        if any(marker in line.casefold() for marker in markers):
            constraints.append(line)
        else:
            requirements.append(line)
    return tuple(requirements), tuple(constraints)


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
    error: str | None = None
    imported: ImportedProject | None = None
    detection: ProjectDetection | None = None
    task: ProductTask | None = None
    plan: ExecutionPlan | None = None
    context: ContextSelection | None = None
    budget: TokenBudget | None = None
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

    def __post_init__(self) -> None:
        self.workspace_root = self.workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteWorkspaceStore(self.workspace_root / "workspace.sqlite3")
        self.driver = CodexDriver(artifact_root=self.workspace_root / "codex-runs")
        self.review_store = ReviewWorkspaceAdapter(self.workspace_root)
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

    def select_project(self, project_id: str, *, restore: bool = False) -> None:
        project = self.store.get_project(project_id)
        detection = self.project_service.detect(project.root)
        with self.lock:
            self.active_project_id = project.project_id
            self.active_task_id = None
            self.imported = ImportedProject(
                source=Path(project.root),
                project_root=Path(project.root),
                workspace_root=Path(project.root).parent,
                skipped_members=(),
            )
            self.detection = detection
            self.task = None
            self.plan = None
            self.context = None
            self.budget = None
            self.graph = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.phase = "task"
            self.error = None
            self.message = "پروژه بازیابی شد." if restore else "پروژه انتخاب شد."
        self.store.set_setting("active_project_id", project.project_id)
        if not restore:
            self.store.set_setting("active_task_id", None)

    def import_path(self, path: str) -> None:
        selected = Path(path).expanduser().resolve()
        imports_root = self.workspace_root / "imports"
        if selected.is_file() and selected.suffix.lower() == ".zip":
            imported = import_project_archive(selected, imports_root)
        elif selected.is_dir():
            imported = import_project_folder(selected, imports_root)
        else:
            raise ValueError("Choose an existing project folder or a ZIP archive.")
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
            self.message = "پروژه در یک کپی ایزوله ذخیره شد."

    @staticmethod
    def _task_from_contract(saved: Any) -> ProductTask:
        contract = saved.contract if hasattr(saved, "contract") else None
        raw_task = contract.get("task") if isinstance(contract, dict) else None
        if not isinstance(raw_task, dict):
            raise TypeError("saved task contract is missing its task payload")
        task = ProductTask(
            task_id=str(raw_task["task_id"]),
            project_root=str(raw_task["project_root"]),
            kind=str(raw_task["kind"]),
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
        context = build_context_selection(task=task, project=self.detection, plan=plan)
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
        with self.lock:
            self.active_task_id = task.task_id
            self.task = task
            self.plan = plan
            self.context = context
            self.budget = budget
            self.graph = graph
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = None
            self.message = "تیکت قبلی بازیابی شد." if restore else "تیکت انتخاب شد."
        self.store.set_setting("active_task_id", task.task_id)

    def create_plan(self, raw_tasks: str, task_id: str | None = None) -> None:
        if self.detection is None or self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        raw = raw_tasks.strip()
        if not raw:
            raise ValueError("Enter at least one task.")
        requirements, user_constraints = _split_task_lines(raw)
        if not requirements:
            raise ValueError("Enter at least one actionable task.")
        task = build_product_task(
            task_id=task_id or uuid.uuid4().hex,
            project_root=str(self.detection.descriptor.root),
            kind="custom",
            title=requirements[0][:96],
            objective="\n".join(requirements),
            requirements_text="\n".join(requirements),
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
            self.graph = graph
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = None
            self.message = "برنامه و مالکیت فایل‌ها آماده شد."
        self.store.set_setting("active_task_id", ready.task_id)

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
        with self.lock:
            self.running = True
            self.phase = "run"
            self.error = None
            self.message = "اجرای Agentها شروع شد."
            self.logs.clear()
        thread = threading.Thread(target=self._run_worker, args=(run.run_id,), daemon=True, name="empy-web-run")
        thread.start()

    def _run_worker(self, workspace_run_id: str) -> None:
        graph = self.graph
        context = self.context
        budget = self.budget
        detection = self.detection
        task = self.task
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
            runtime = CodexGraphRuntime(driver=self.driver, run_root=self.workspace_root / "codex-runs")
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
                self.node_states[node.node_id] = "completed" if node.status == "completed" else "failed"
            if result.status != "completed":
                raise RuntimeError(result.error_message or f"Codex run ended as {result.status}")
            verification = VerificationRuntime().run(
                detection=detection,
                evidence_root=self.workspace_root / "verification-evidence",
                on_event=self._verification_event,
            )
            if verification.finalize_allowed:
                verification = finalize_verification(verification)
            review = self.review_store.create(detection.descriptor.root)
            self.verification = verification
            self.review = review
            self.store.update_run(
                workspace_run_id,
                state="completed" if verification.finalize_allowed else "failed",
                summary="Run and verification completed" if verification.finalize_allowed else "Verification failed",
                driver_name="codex",
                evidence_path=verification.evidence_path,
            )
            if self.active_task_id is not None:
                self.store.update_task(self.active_task_id, status="review")
            with self.lock:
                self.running = False
                self.phase = "result"
                self.message = "نتیجه برای Review آماده است."
        except (OSError, RuntimeError, ValueError) as exc:
            self._record_failure(workspace_run_id, str(exc))

    def _record_failure(self, workspace_run_id: str, message: str) -> None:
        try:
            self.store.update_run(workspace_run_id, state="failed", summary=message, driver_name="codex")
        except KeyError:
            pass
        with self.lock:
            self.running = False
            self.phase = "run"
            self.error = message
            self.message = "اجرا متوقف شد."
        self.add_log(message, "error")

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
        self.review = report
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="accepted" if decision == "accept" else "reverted")
        self.message = "تصمیم روی تغییرات ثبت شد."

    def export_project(self, destination: str | None = None) -> None:
        if self.detection is None or self.review is None:
            raise RuntimeError("There is no reviewed project to export.")
        if self.review.pending_count:
            raise RuntimeError("Accept or revert every changed file first.")
        if self.verification is None or self.verification.finalized_at is None:
            raise RuntimeError("Verification must pass before export.")
        target = Path(destination).expanduser() if destination else (
            self.workspace_root / "releases" / f"{self.detection.descriptor.display_name}-{uuid.uuid4().hex[:8]}.zip"
        )
        exported = export_project_zip(self.detection.descriptor.root, target)
        self.export = exported
        self.message = "فایل ZIP تک‌ریشه و قابل استخراج آماده شد."
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="released")

    def reset(self) -> None:
        with self.lock:
            self.active_project_id = None
            self.active_task_id = None
            self.imported = None
            self.detection = None
            self.task = None
            self.plan = None
            self.context = None
            self.budget = None
            self.graph = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.phase = "project"
            self.error = None
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
                }
            review = self.review.to_dict() if self.review is not None else None
            verification = self.verification.to_dict() if self.verification is not None else None
            return _json_safe(
                {
                    "language": self.language,
                    "phase": "saved" if self.export else self.phase,
                    "message": self.message,
                    "error": self.error,
                    "projects": self._project_records(),
                    "active_project": project,
                    "active_task_id": self.active_task_id,
                    "tasks": tasks,
                    "task": asdict(self.task) if self.task is not None else None,
                    "plan": plan,
                    "running": self.running,
                    "logs": list(self.logs),
                    "verification": verification,
                    "review": review,
                    "export": self.export.to_dict() if self.export is not None else None,
                    "engine": {
                        "provider": inspection.display_name,
                        "availability": inspection.availability,
                        "ready": inspection.availability == "available" and inspection.authenticated,
                        "version": inspection.version,
                        "message": inspection.message,
                        "remediation": inspection.remediation,
                    },
                }
            )


def _native_picker(kind: str) -> str | None:
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

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("request body must be an object")
        return value

    def _send_static(self, target: Path, content_type: str) -> None:
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
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
            content_type = "text/css" if target.suffix == ".css" else "application/javascript"
            self._send_static(target, content_type)
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
            body = self._read_json()
            result = self._handle_post(urlparse(self.path).path, body)
            self._send_json(result)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self.app.state.error = str(exc)
            self._send_json({"error": str(exc), "state": self.app.state.public()}, 400)

    def _handle_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        state = self.app.state
        if path == "/api/import":
            state.import_path(str(body.get("path", "")))
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
        elif path == "/api/run":
            state.start_run()
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
            subprocess.run(["/usr/bin/open", "codex://threads/new"], check=False)
        elif path == "/api/reveal-export":
            if state.export is not None:
                subprocess.run(["/usr/bin/open", "-R", str(state.export.archive_path)], check=False)
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
    workspace = args.workspace or (Path.home() / "Library" / "Application Support" / "Empy Studio")
    server = create_server(workspace=workspace, token=args.token, port=args.port)
    host, actual_port = server.server_address
    url = f"http://{host}:{actual_port}/?token={server.token}"
    print(url, flush=True)
    if not args.no_open:
        subprocess.Popen(["/usr/bin/open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
