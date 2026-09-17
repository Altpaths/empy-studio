from __future__ import annotations

import argparse
import hashlib
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
from urllib.parse import parse_qs, quote, unquote, urlparse

from empy_studio.benchmark import BenchmarkResult, run_local_benchmark
from empy_studio.core import (
    AgentRunGraph,
    ContextPolicy,
    ContextSelection,
    DefaultProjectService,
    ExecutionPlan,
    ProductTask,
    ProjectDetection,
    ProviderRoute,
    RoutingPolicy,
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
from empy_studio.core.failure_memory import (
    FailureMemoryRecord,
)
from empy_studio.core.failure_memory import (
    failure_fingerprint as failure_memory_fingerprint,
)
from empy_studio.core.failure_memory import (
    normalize_relative_path as normalize_memory_relative_path,
)
from empy_studio.core.path_policy import (
    is_agent_denied_relative_path,
    normalize_relative_path,
    project_path,
)
from empy_studio.core.project_brain import (
    ProjectBrainIndex,
    build_load_save_project_brain_index,
)
from empy_studio.core.recovery import RecoveryPolicy, RecoveryState, external_block
from empy_studio.core.token_budget import policy_for_preset
from empy_studio.dependency_bootstrap import (
    DependencyBootstrapResult,
    prepare_project_dependencies,
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
    CodexNodeDriver,
    CodexProgressEvent,
    RoutedCodexNodeDriver,
)
from empy_studio.drivers.omniroute import CodexRouteConfig, OmniRouteCodexDriver
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
    inspect_project_delta,
    review_snapshot_drift,
    safe_upload_relative_path,
    summarize_import_skips,
    validate_export_artifacts,
)
from empy_studio.release_validation import validate_changed_html_links
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
    verification_preflight,
    verification_staleness_reason,
)
from empy_studio.workspace import SQLiteWorkspaceStore

WEB_ROOT = Path(__file__).with_name("web")
MAX_AUTOMATIC_REPAIR_ATTEMPTS = 10
MAX_VISIBLE_PROJECTS = 5
DEFAULT_CONSTRAINTS = (
    "Do not change unrelated features or business behavior.\n"
    "Do not read secrets or environment files, and do not modify logs, generated dependency directories (vendor or node_modules), or Git history.\n"
    "Project verification may use dependencies already present in the isolated copy; do not include those dependency directories in Agent context or the final ZIP.\n"
    "Do not commit, push, merge, tag, publish, or alter remotes."
)
DEFAULT_DEFINITION_OF_DONE = (
    "Every requested task is implemented.\n"
    "Only files required by the approved work are changed.\n"
    "Relevant tests, build, and lint checks pass when available.\n"
    "A readable review and a verified change-only deployment archive are produced."
)


@dataclass(frozen=True)
class _FailureMemoryScope:
    """Stable local identity for one planned provider target.

    Failure memory intentionally stores only these digests and relative paths.
    The digests let the runtime distinguish an unchanged redundant retry from
    a real corrective attempt without placing project contents in SQLite or a
    provider prompt.
    """

    target_digest: str
    snapshot_digest: str
    target_paths: tuple[str, ...]
    snapshot_paths: tuple[str, ...]

    @property
    def evidence(self) -> tuple[str, ...]:
        return (
            f"scope_target:{self.target_digest}",
            f"scope_snapshot:{self.snapshot_digest}",
        )


def _scope_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_workspace_root() -> Path:
    """Create a new per-launch workspace for a clean product trial."""

    normal_root: Path = Path(default_workspace_root())
    clean_root = normal_root.parent / f"{normal_root.name} Clean"
    clean_root.mkdir(parents=True, exist_ok=True)
    session_root = clean_root / f"session-{uuid.uuid4().hex}"
    session_root.mkdir()
    return session_root


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


def _failure_kind(detail: str) -> str:
    """Classify a failure into a user-actionable category without guessing a fix."""

    normalized = detail.casefold()
    if any(
        marker in normalized
        for marker in (
            "outside this node's ownership",
            "outside this wave's ownership",
            "outside the node's ownership",
            "outside the allowed files",
            "not in the list of allowed",
            "not in the allowed file",
            "ownership mismatch",
            "ownership boundary",
            "فایل مالکیت‌داده‌شده",
            "فهرست فایل‌های مجاز",
            "محدودهٔ مجاز",
            "محدوده مجاز",
            "گسترش مالکیت فایل",
        )
    ):
        return "ownership_mismatch"
    if any(
        marker in normalized
        for marker in (
            "produced no project change",
            "no project change",
            "no project file was changed",
            "no file change",
        )
    ):
        return "no_change"
    if any(
        marker in normalized
        for marker in (
            "no writable files for writing roles",
            "no writable files",
            "فایل قابل‌ویرایش",
            "فایل قابل ویرایش",
            "فایل امن و قابل‌ویرایشی",
            "فایل امن و قابل ویرایشی",
            "قابل‌ویرایشی",
            "قابل ویرایشی",
        )
    ):
        return "no_writable_files"
    if any(
        marker in normalized
        for marker in (
            "dirty_worktree",
            "clean git worktree",
            "commit or restore these paths first",
            "could not safely preserve the previous isolated changes",
            "isolated workspace is still not clean",
        )
    ):
        return "dirty_worktree"
    if any(
        marker in normalized
        for marker in (
            "budget_exceeded",
            "fresh-token limit",
            "token budget",
            "token guard",
            "سقف مصرف",
        )
    ):
        return "token_budget"
    if (
        "vendor/autoload.php" in normalized
        or "composer" in normalized and "missing" in normalized
        or "dependency preparation" in normalized
        or "dependency bootstrap" in normalized
        or "composer.lock" in normalized
        or "package-lock.json" in normalized
    ):
        return "missing_dependency"
    if "no safe verification checks" in normalized or "verification.json" in normalized:
        return "missing_verification_contract"
    if any(marker in normalized for marker in ("permission denied", "permissionerror", "access is denied")):
        return "permission"
    if any(marker in normalized for marker in ("timed out", "timeout", "time limit")):
        return "timeout"
    if "verification contract" in normalized or "check expects" in normalized:
        return "verification_contract_mismatch"
    if any(marker in normalized for marker in ("missing", "not found", "does not exist", "no such file")):
        return "missing_file_or_route"
    return "check_failed"


def _add_entrypoint_hint(
    detail: str,
    detection: ProjectDetection | None,
) -> tuple[str, str | None]:
    """Explain a common HTML/PHP contract mismatch without changing the project."""

    if detection is None or "index.html" not in detail.casefold():
        return detail, None
    root = detection.effective_verification_root
    if (root / "index.html").is_file() or not (root / "index.php").is_file():
        return detail, None
    hint = (
        "Root-cause hint: the verification check expects index.html, but "
        "the detected application entry point is index.php."
    )
    if hint not in detail:
        detail = f"{detail}\n{hint}"
    return detail, "verification_contract_mismatch"


def _plain_failure_finding(
    kind: str,
    detail: str,
    *,
    language: str,
) -> str:
    """Give a nontechnical user the one fact that blocks delivery."""

    normalized = detail.casefold()
    if kind == "no_change":
        return (
            "Agent هیچ تغییری در فایل‌های پروژه ثبت نکرد و نتیجهٔ PASS قابل‌تأیید ارائه نداد؛ "
            "برای جلوگیری از موفقیت جعلی، Verification و ZIP متوقف شدند."
            if language == "fa"
            else "The Agent produced no project change and did not provide a verifiable PASS attestation; Verification and ZIP creation were stopped to avoid a false success."
        )
    if kind == "no_writable_files":
        return (
            "برای این تیکت فایل امن و قابل‌ویرایشی برای نقش اجرایی پیدا نشد؛ Empy باید فهرست فایل‌ها را دوباره بررسی یا هدف فایل جدید را بسازد."
            if language == "fa"
            else "No safe writable target was assigned to the implementation role; Empy must re-check the project index or create the approved missing target."
        )
    if kind == "ownership_mismatch":
        return (
            "هدف فایل این نود با ساختار واقعی پروژه منطبق نبود؛ Agent اجازهٔ تغییر فایل لازم را نداشت و هیچ تغییر تأییدشده‌ای ثبت نشد."
            if language == "fa"
            else "The node's file target did not match the project's real layout; the Agent was not allowed to change the required file, so no approved change was recorded."
        )
    if kind == "verification_contract_mismatch" and "index.html" in normalized:
        expected_path = "index.html"
        if "public_html/index.html" in normalized:
            expected_path = "public_html/index.html"
        elif "public/" in normalized and "public/index.html" in normalized:
            expected_path = "public/index.html"
        elif "www/index.html" in normalized:
            expected_path = "www/index.html"
        elif "web/index.html" in normalized:
            expected_path = "web/index.html"
        actual_path = expected_path.removesuffix("index.html") + "index.php"
        if language == "fa":
            return (
                f"صفحهٔ اول ساخته نشد: تست دنبال «{expected_path}» است، "
                f"اما فایل واقعی پروژه «{actual_path}» است."
            )
        return (
            "The home page was not delivered: the check expects "
            f"{expected_path}, but the project has {actual_path}."
        )
    if kind == "missing_dependency":
        return (
            "یک وابستگی لازم پیدا نشد؛ Empy باید آن را در کپی ایزوله تأمین کند."
            if language == "fa"
            else "A required dependency is missing; Empy must provide it in the isolated copy."
        )
    if kind == "dirty_worktree":
        return (
            "تلاش قبلی در کپی ایزوله تغییر ذخیره‌نشده دارد؛ Empy باید آن تلاش را امن کنار بگذارد و از آخرین مبنای تأییدشده ادامه دهد."
            if language == "fa"
            else "The previous attempt left unreviewed changes in the isolated copy; Empy must preserve that attempt and continue from the last accepted baseline."
        )
    if kind == "permission":
        return (
            "دسترسی لازم برای خواندن یا نوشتن فایل وجود ندارد."
            if language == "fa"
            else "Empy does not have permission to read or write a required file."
        )
    if kind == "missing_verification_contract":
        return (
            "فایل یا دستور تست پروژه مشخص نیست؛ Empy نمی‌تواند نتیجهٔ واقعی را تأیید کند."
            if language == "fa"
            else "The project does not define a usable verification command."
        )
    if kind == "token_budget":
        return (
            "سقف مصرف توکن این مرحله پر شد؛ نتیجهٔ کامل تولید نشده و ZIP ساخته نمی‌شود."
            if language == "fa"
            else "This step reached Empy's safe token limit; no complete result or ZIP was produced."
        )
    if language == "fa":
        return "بررسی نهایی پروژه موفق نشد؛ Empy هنوز ZIP قابل‌تحویل تولید نمی‌کند."
    return "The final project check failed; Empy cannot create a deliverable ZIP yet."


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
        "fresh_input_tokens": usage.fresh_input,
        "uncached_total_tokens": usage.uncached_total,
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
    restore_session: bool = field(default=True, kw_only=True)
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
    failure_context: dict[str, Any] | None = None
    failure_memory_hint: str = field(default="", init=False)
    failure_memory_matches: tuple[FailureMemoryRecord, ...] = field(
        default_factory=tuple,
        init=False,
        repr=False,
    )
    failure_memory_open_count: int = field(default=0, init=False)
    failure_memory_blocked: bool = field(default=False, init=False)
    failure_memory_block_reason: str | None = field(default=None, init=False)
    repair_attempts: int = 0
    recovery: RecoveryState = field(default_factory=RecoveryState)
    recovery_deadline: threading.Timer | None = field(default=None, repr=False)
    model_route: CodexRouteConfig = field(default_factory=CodexRouteConfig)
    _starting_run: bool = field(default=False, init=False, repr=False)
    route_settings_error: str | None = field(default=None, init=False)
    budget_preset: str = "economy"
    compact_retry: bool = False
    carry_forward_base_revision: str | None = None
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
    dependency_bootstrap: DependencyBootstrapResult | None = field(
        default=None,
        repr=False,
    )
    logs: list[dict[str, str]] = field(default_factory=list)
    node_states: dict[str, str] = field(default_factory=dict)
    running: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    driver: CodexNodeDriver = field(init=False, repr=False)
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
        saved_route = self.store.get_setting("model-route.v1")
        try:
            self.model_route = CodexRouteConfig.from_dict({} if saved_route is None else saved_route)
        except (TypeError, ValueError):
            self.model_route = CodexRouteConfig(mode="omniroute")
            self.route_settings_error = "Saved model connection is invalid; choose and save a connection before running."
            self.error = self.route_settings_error
        self.driver = self._route_driver(self.model_route)
        self.review_store = ReviewWorkspaceAdapter(self.workspace_root)
        self.execution_store = CodexExecutionWorkspaceAdapter(self.workspace_root)
        self.verification_store = VerificationWorkspaceAdapter(self.workspace_root)
        saved_language = self.store.get_setting("language", "fa")
        self.language = saved_language if saved_language in {"fa", "en"} else "fa"
        if not self.restore_session:
            return
        saved_project = self.store.get_setting("active_project_id")
        if isinstance(saved_project, str):
            try:
                self.select_project(saved_project, restore=True)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
                # A saved project can outlive the folder it pointed to. Keep the
                # project record visible so the user can re-import it instead of
                # making the whole UI fail during startup.
                with self.lock:
                    self.active_project_id = None
                    self.active_task_id = None
                    self.phase = "project"
                    self.message_level = "warning"
                    self.error = safe_user_error(exc, language=self.language)
                    self.message = ""
                self.store.set_setting("active_project_id", None)
                self.store.set_setting("active_task_id", None)
            saved_task = self.store.get_setting("active_task_id")
            if self.active_project_id is not None and isinstance(saved_task, str):
                try:
                    self.select_task(saved_task, restore=True)
                except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                    self.store.set_setting("active_task_id", None)

    def _route_driver(self, route: CodexRouteConfig) -> CodexNodeDriver:
        if route.mode == "omniroute":
            models = (route.model, *route.fallback_models)
            if len(models) == 1:
                return OmniRouteCodexDriver(
                    route=route,
                    artifact_root=self.workspace_root / "codex-runs",
                )
            candidates: list[tuple[ProviderRoute, CodexNodeDriver]] = []
            for index, model in enumerate(models, start=1):
                candidate_route = replace(
                    route,
                    model=model,
                    fallback_models=(),
                )
                candidates.append(
                    (
                        ProviderRoute(
                            provider_id=f"omniroute-{index}",
                            display_name=f"Codex via OmniRoute ({model})",
                            kind="omniroute",
                            model=model,
                            cost_class=("paid" if route.allow_paid and model not in {"oc/north-mini-code-free", "oc/big-pickle"} else "local"),
                            allow_paid=route.allow_paid,
                            credential_environment_variable=route.env_key,
                        ),
                        OmniRouteCodexDriver(
                            route=candidate_route,
                            artifact_root=self.workspace_root / "codex-runs",
                        ),
                    )
                )
            return RoutedCodexNodeDriver(
                candidates=tuple(candidates),
                policy=RoutingPolicy(
                    allow_paid=route.allow_paid,
                    max_attempts=len(candidates),
                ),
            )
        return CodexDriver(artifact_root=self.workspace_root / "codex-runs")

    def set_model_route(self, value: dict[str, Any]) -> None:
        with self.lock:
            if self.running or self._starting_run or (self.recovery.started_at is not None and self.recovery.stop_reason is None):
                raise RuntimeError("Stop the workflow before changing its model route.")
            route = CodexRouteConfig.from_dict(value)
            route.validate()
            driver = self._route_driver(route)
            self.store.set_setting("model-route.v1", route.to_dict())
            self.model_route = route
            self.route_settings_error = None
            self.driver = driver
            self.message = "مسیر مدل ذخیره شد؛ وضعیت اتصال را بررسی کنید."
            self.error = None

    def add_log(self, message: str, level: str = "info") -> None:
        with self.lock:
            self.logs.append({"time": _now(), "level": level, "text": message.rstrip()})
            self.logs = self.logs[-300:]

    def _project_records(self) -> list[dict[str, Any]]:
        # Keep the complete history in SQLite, but expose only a bounded,
        # newest-first list to the UI and state API so the start screen stays
        # usable as projects accumulate.
        return [
            self._project_record(project)
            for project in self.store.list_projects()[:MAX_VISIBLE_PROJECTS]
        ]

    def _project_record(self, project: Any) -> dict[str, Any]:
        project_root = Path(project.root)
        return {
            "id": project.project_id,
            "name": project.display_name,
            "root": project.root,
            "type": project.project_type,
            "available": project_root.is_dir(),
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

    def _active_project(self) -> dict[str, Any] | None:
        if self.active_project_id is None:
            return None
        try:
            project = self.store.get_project(self.active_project_id)
        except KeyError:
            return None
        return self._project_record(project)

    def _brain_index_path(self, project_id: str) -> Path:
        return self.workspace_root / "project-brain" / f"{project_id}.json"

    @staticmethod
    def _import_report_setting_key(project_id: str) -> str:
        return f"import-report:{project_id}"

    @staticmethod
    def _failure_context_setting_key(project_id: str) -> str:
        return f"failure-context:{project_id}"

    @staticmethod
    def _repair_attempts_setting_key(project_id: str) -> str:
        return f"repair-attempts:{project_id}"

    @staticmethod
    def _carry_forward_setting_key(project_id: str) -> str:
        return f"carry-forward-base:{project_id}"

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
        raw_readiness = value.get("verification_readiness")
        verification_readiness: dict[str, Any] | None = None
        if raw_readiness is not None:
            if not isinstance(raw_readiness, dict):
                return None
            readiness_status = raw_readiness.get("status")
            readiness_checks = raw_readiness.get("checks")
            readiness_diagnostics = raw_readiness.get("diagnostics")
            if (
                readiness_status not in {"ready", "needs_attention"}
                or not isinstance(readiness_checks, list)
                or not all(isinstance(item, str) for item in readiness_checks)
                or not isinstance(readiness_diagnostics, list)
                or not all(isinstance(item, str) for item in readiness_diagnostics)
            ):
                return None
            verification_readiness = {
                "status": readiness_status,
                "checks": [str(item) for item in readiness_checks[:32]],
                "diagnostics": [str(item) for item in readiness_diagnostics[:8]],
            }
        return {
            "status": status,
            "copied_files": copied_files,
            "skipped_files": skipped_files,
            "categories": normalized_categories,
            "verification_readiness": verification_readiness,
        }

    def _load_failure_context(self, project_id: str) -> dict[str, Any] | None:
        value = self.store.get_setting(self._failure_context_setting_key(project_id))
        if not isinstance(value, dict):
            return None
        diagnostics = value.get("diagnostics")
        failures = value.get("failures")
        if not isinstance(diagnostics, list) or not all(
            isinstance(item, str) for item in diagnostics
        ):
            return None
        if not isinstance(failures, list) or not all(
            isinstance(item, dict) for item in failures
        ):
            return None
        return {
            "kind": str(value.get("kind", "check_failed")),
            "diagnostics": [str(item) for item in diagnostics[:8]],
            "failures": [dict(item) for item in failures[:8]],
            "evidence": str(value.get("evidence", "")),
            "created_at": str(value.get("created_at", "")),
        }

    def _failure_memory_target_paths(
        self,
        *,
        graph: AgentRunGraph | None = None,
        context: ContextSelection | None = None,
    ) -> tuple[str, ...]:
        """Return exact file targets used by the current graph.

        Directory scopes and unsafe provider output are deliberately ignored.
        Context files are a fallback for read-only plans and are also included
        in the snapshot below because a changed dependency/configuration file
        must make a later attempt eligible for a fresh run.
        """

        values: set[str] = set()
        selected_graph = self.graph if graph is None else graph
        selected_context = self.context if context is None else context
        if selected_graph is not None:
            for node in selected_graph.nodes:
                for raw_path in node.owned_files:
                    try:
                        values.add(normalize_memory_relative_path(raw_path))
                    except (TypeError, ValueError):
                        continue
        if not values and selected_context is not None:
            for pack in selected_context.packs:
                for item in pack.files:
                    try:
                        values.add(normalize_memory_relative_path(item.relative_path))
                    except (TypeError, ValueError):
                        continue
        return tuple(sorted(values))

    def _failure_memory_snapshot_paths(
        self,
        *,
        graph: AgentRunGraph | None = None,
        context: ContextSelection | None = None,
    ) -> tuple[str, ...]:
        values = set(self._failure_memory_target_paths(graph=graph, context=context))
        selected_context = self.context if context is None else context
        if selected_context is not None:
            for pack in selected_context.packs:
                for item in pack.files:
                    try:
                        values.add(normalize_memory_relative_path(item.relative_path))
                    except (TypeError, ValueError):
                        continue
        return tuple(sorted(values))

    def _failure_memory_scope(
        self,
        *,
        task: ProductTask | None = None,
        graph: AgentRunGraph | None = None,
        context: ContextSelection | None = None,
    ) -> _FailureMemoryScope:
        """Hash only local target metadata and relevant file contents.

        This is a content identity, not a prompt context.  It is therefore
        cheap to compute, contains no source text, and makes the duplicate-run
        guard sensitive to a real target or source change.
        """

        selected_graph = self.graph if graph is None else graph
        target_paths = self._failure_memory_target_paths(graph=graph, context=context)
        snapshot_paths = self._failure_memory_snapshot_paths(graph=graph, context=context)
        owner_map: list[tuple[str, tuple[str, ...]]] = []
        if selected_graph is not None:
            for node in sorted(selected_graph.nodes, key=lambda item: item.node_id):
                owned: list[str] = []
                for raw_path in node.owned_files:
                    try:
                        owned.append(normalize_memory_relative_path(raw_path))
                    except (TypeError, ValueError):
                        continue
                owner_map.append((str(node.agent_role), tuple(sorted(set(owned)))))
        if not owner_map:
            request_identity = failure_memory_fingerprint(
                self._failure_memory_request_text(task=task),
                kind="request",
            )
            owner_map.append(("request", (request_identity,)))
        target_digest = _scope_digest(
            {
                "owners": owner_map,
                "target_paths": target_paths,
            }
        )
        snapshot_entries: list[tuple[str, str]] = []
        root = self.detection.descriptor.root if self.detection is not None else None
        for relative_path in snapshot_paths:
            digest = "missing"
            if root is not None:
                try:
                    candidate = project_path(root, relative_path, allow_directory=False)
                    if candidate.is_file() and not candidate.is_symlink():
                        hasher = hashlib.sha256()
                        with candidate.open("rb") as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                hasher.update(chunk)
                        digest = hasher.hexdigest()
                    elif candidate.exists():
                        digest = "non_file"
                except (OSError, RuntimeError, TypeError, ValueError):
                    digest = "unreadable"
            snapshot_entries.append((relative_path, digest))
        snapshot_digest = _scope_digest(snapshot_entries)
        return _FailureMemoryScope(
            target_digest=target_digest,
            snapshot_digest=snapshot_digest,
            target_paths=target_paths,
            snapshot_paths=snapshot_paths,
        )

    def _failure_memory_request_text(self, *, task: ProductTask | None = None) -> str:
        selected_task = self.task if task is None else task
        if selected_task is not None and selected_task.objective.strip():
            return selected_task.objective
        if self.recovery.original_request.strip():
            return self.recovery.original_request
        if self.active_task_id is not None:
            try:
                return self.store.get_task(self.active_task_id).request_text
            except (KeyError, OSError, TypeError, ValueError):
                pass
        return "unknown request"

    @staticmethod
    def _failure_memory_record_scope(record: FailureMemoryRecord) -> dict[str, str]:
        values: dict[str, str] = {}
        for item in record.evidence:
            for key in ("scope_target", "scope_snapshot"):
                prefix = f"{key}:"
                if item.startswith(prefix):
                    value = item[len(prefix) :]
                    if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
                        values[key] = value
        return values

    @staticmethod
    def _failure_memory_fingerprint(
        summary: str,
        *,
        kind: str,
        action: str,
        scope: _FailureMemoryScope,
    ) -> str:
        root = failure_memory_fingerprint(summary, kind=kind, action=action)
        return hashlib.sha256(
            f"{root}|target={scope.target_digest}|snapshot={scope.snapshot_digest}".encode()
        ).hexdigest()

    @staticmethod
    def _failure_memory_action(kind: str) -> str:
        safe_kind = kind.strip() or "check_failed"
        return (
            f"Resolve the confirmed {safe_kind} failure in the isolated project, "
            "then rerun deterministic Verification."
        )[:800]

    @staticmethod
    def _failure_memory_is_external(record: FailureMemoryRecord) -> bool:
        if record.kind in {
            "missing_dependency",
            "permission",
            "dirty_worktree",
            "timeout",
        }:
            return True
        normalized = record.summary.casefold()
        return any(
            marker in normalized
            for marker in (
                "credential",
                "api key",
                "authentication",
                "authenticated",
                "provider unavailable",
                "choose and save a connection",
            )
        )

    def _failure_memory_record_from_context(
        self,
        context: dict[str, Any],
    ) -> FailureMemoryRecord | None:
        if self.active_project_id is None:
            return None
        failures = context.get("failures")
        diagnostics = context.get("diagnostics")
        first_failure = (
            next(
                (
                    item
                    for item in failures
                    if isinstance(item, dict) and str(item.get("detail", "")).strip()
                ),
                None,
            )
            if isinstance(failures, list)
            else None
        )
        if first_failure is not None:
            summary = str(first_failure.get("detail", "")).strip()
            kind = str(first_failure.get("kind", "")).strip() or str(
                context.get("kind", "check_failed")
            )
        else:
            summary = (
                next(
                    (str(item).strip() for item in diagnostics if str(item).strip()),
                    "The Empy workflow stopped without a diagnostic.",
                )
                if isinstance(diagnostics, list)
                else "The Empy workflow stopped without a diagnostic."
            )
            kind = str(context.get("kind", "check_failed"))
        action = self._failure_memory_action(kind)
        scope = self._failure_memory_scope()
        evidence: list[str] = [*scope.evidence]
        if isinstance(diagnostics, list):
            evidence.extend(str(item) for item in diagnostics[:3] if str(item).strip())
        if isinstance(failures, list):
            evidence.extend(
                str(item.get("detail", ""))
                for item in failures[:3]
                if isinstance(item, dict) and str(item.get("detail", "")).strip()
            )
        fingerprint = self._failure_memory_fingerprint(
            summary,
            kind=kind,
            action=action,
            scope=scope,
        )
        try:
            return self.store.record_failure(
                project_id=self.active_project_id,
                task_id=self.active_task_id,
                fingerprint=fingerprint,
                kind=kind,
                summary=summary,
                action=action,
                affected_paths=scope.target_paths or scope.snapshot_paths,
                evidence=evidence,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            # Failure memory is an optimization and a durable hint.  A
            # malformed row or unavailable workspace must never turn a real
            # project failure into a second application failure.
            self.add_log("Failure memory could not persist this diagnostic; continuing safely.", "warning")
            return None

    def _refresh_failure_memory_view(
        self,
        *,
        task: ProductTask | None = None,
        graph: AgentRunGraph | None = None,
        context: ContextSelection | None = None,
    ) -> None:
        """Refresh bounded project-local memory state for API/UI consumers."""

        project_id = self.active_project_id
        if project_id is None:
            self.failure_memory_matches = ()
            self.failure_memory_open_count = 0
            self.failure_memory_hint = ""
            self.failure_memory_blocked = False
            self.failure_memory_block_reason = None
            return
        scope = self._failure_memory_scope(task=task, graph=graph, context=context)
        try:
            records = self.store.list_failures(
                project_id,
                include_resolved=False,
                limit=32,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            self.failure_memory_matches = ()
            self.failure_memory_open_count = 0
            self.failure_memory_hint = ""
            self.failure_memory_blocked = False
            self.failure_memory_block_reason = None
            return
        exact: list[FailureMemoryRecord] = []
        related: list[FailureMemoryRecord] = []
        for record in records:
            metadata = self._failure_memory_record_scope(record)
            expected = self._failure_memory_fingerprint(
                record.summary,
                kind=record.kind,
                action=record.action,
                scope=scope,
            )
            if (
                metadata.get("scope_target") == scope.target_digest
                and metadata.get("scope_snapshot") == scope.snapshot_digest
                and record.fingerprint == expected
            ):
                exact.append(record)
            if (
                not record.affected_paths
                or not scope.snapshot_paths
                or set(record.affected_paths).intersection(scope.snapshot_paths)
            ):
                related.append(record)
        self.failure_memory_matches = tuple(exact[:8])
        self.failure_memory_open_count = len(records)
        try:
            hint = self.store.failure_context_hint(
                project_id,
                affected_paths=scope.snapshot_paths,
                limit=4,
            )
            if not hint and any(not record.affected_paths for record in related):
                hint = self.store.failure_context_hint(project_id, limit=4)
        except (OSError, RuntimeError, TypeError, ValueError):
            hint = ""
        self.failure_memory_hint = hint[:2400]
        hard_block = [
            record
            for record in exact
            if not self._failure_memory_is_external(record)
        ]
        # Automatic repair has already changed the recovery cycle and is an
        # intentional corrective pass.  It must be allowed to call the
        # provider; RecoveryState remains the independent attempt/token guard.
        if self.recovery.attempts > 0:
            hard_block = []
        self.failure_memory_blocked = bool(hard_block)
        self.failure_memory_block_reason = None
        if hard_block:
            first = hard_block[0]
            if self.language == "en":
                self.failure_memory_block_reason = (
                    "This provider run was stopped because the same confirmed failure "
                    "is already recorded for the unchanged target and project files. "
                    "Change the target or fix the cause first, then run again."
                )
            else:
                self.failure_memory_block_reason = (
                    "این اجرای Provider متوقف شد چون همان علت شکستِ تأییدشده برای هدف و فایل‌های "
                    "بدون تغییر در حافظه ثبت شده است. ابتدا علت یا هدف را اصلاح کنید و سپس دوباره اجرا کنید."
                )
            self.add_log(
                f"Duplicate provider run blocked by failure memory ({first.kind}).",
                "warning",
            )
        # ``related`` is deliberately not sent wholesale to the provider; the
        # store renders only summary/action/relative paths and enforces the
        # final character bound.  Keep the view project-scoped and bounded.

    def _resolve_failure_memory_after_verification(
        self,
        verification: VerificationReport,
    ) -> None:
        """Close only incidents covered by a real final verification pass."""

        if (
            self.active_project_id is None
            or not verification.finalize_allowed
            or verification.status != "pass"
        ):
            return
        scope = self._failure_memory_scope()
        try:
            records = self.store.list_failures(
                self.active_project_id,
                include_resolved=False,
                limit=64,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        evidence = {
            "status": "pass",
            "verified": True,
            "result": "All deterministic Verification checks passed.",
            "verification_id": verification.verification_id,
        }
        for record in records:
            metadata = self._failure_memory_record_scope(record)
            same_task = self.active_task_id is not None and self.active_task_id in record.task_ids
            same_target = metadata.get("scope_target") == scope.target_digest
            if not (same_task or same_target):
                continue
            try:
                self.store.resolve_failure(
                    record.memory_id,
                    evidence,
                    verification_id=verification.verification_id,
                )
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                # One malformed or concurrently deleted row must not prevent
                # the verified result from reaching Review/ZIP generation.
                continue
        self._refresh_failure_memory_view()

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

    def _baseline_snapshot_path(self) -> Path:
        """Return the immutable full copy used for tests and delta export."""

        if self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        snapshot = (
            self.workspace_root
            / "vaults"
            / self.active_project_id
            / "baseline"
            / "source.zip"
        )
        if not snapshot.is_file():
            raise RuntimeError(
                "Empy baseline snapshot is missing; re-import the project."
            )
        return snapshot

    @staticmethod
    def _load_release_manifest(path: Path) -> dict[str, Any] | None:
        try:
            if not path.is_file():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def select_project(self, project_id: str, *, restore: bool = False) -> None:
        if self.running:
            raise RuntimeError("Stop the active run before switching projects.")
        project = self.store.get_project(project_id)
        if not Path(project.root).is_dir():
            raise ValueError(
                "saved project is no longer available; re-import its folder or ZIP."
            )
        detection = self.project_service.detect(project.root)
        import_report = self._load_import_report(project.project_id)
        if import_report is not None:
            import_report = {
                **import_report,
                "verification_readiness": verification_preflight(detection).to_dict(),
            }
            self.store.set_setting(
                self._import_report_setting_key(project.project_id),
                import_report,
            )
        recovery = RecoveryState.from_dict(self.store.get_setting(f"recovery.v1.{project.project_id}"))
        if recovery.status == "running":
            recovery.stop("interrupted: The application stopped during execution; inspect preserved work and explicitly resume.")
            self.store.set_setting(f"recovery.v1.{project.project_id}", recovery.to_dict())
        failure_context = self._load_failure_context(project.project_id)
        saved_repair_attempts = self.store.get_setting(
            self._repair_attempts_setting_key(project.project_id),
            0,
        )
        repair_attempts = (
            saved_repair_attempts
            if isinstance(saved_repair_attempts, int)
            and 0 <= saved_repair_attempts <= MAX_AUTOMATIC_REPAIR_ATTEMPTS
            else 0
        )
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
            self.dependency_bootstrap = None
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
            self.failure_context = failure_context
            self.recovery = recovery
            self.budget_preset = "economy"
            self.repair_attempts = recovery.attempts or repair_attempts
            self.compact_retry = False
            self.message = "پروژه بازیابی شد." if restore else "پروژه انتخاب شد."
        self.store.set_setting("active_project_id", project.project_id)
        if not restore:
            self.store.set_setting("active_task_id", None)
        self._refresh_brain_index()
        self._refresh_failure_memory_view()

    def _register_import(self, imported: ImportedProject) -> None:
        detection = self.project_service.detect(imported.project_root)
        verification_readiness = verification_preflight(detection).to_dict()
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
                "verification_readiness": verification_readiness,
            }
            self.import_report = import_report
            self.repair_attempts = 0
            needs_attention = verification_readiness["status"] != "ready"
            readiness_diagnostics = cast(
                list[str],
                verification_readiness["diagnostics"],
            )
            if needs_attention and readiness_diagnostics:
                self.message_level = "warning"
                self.message = (
                    "Import completed, but Verification needs attention before "
                    f"an Agent run: {readiness_diagnostics[0]}"
                    if self.language == "en"
                    else "واردسازی کامل شد، اما قبل از اجرای Agent یک پیش‌نیاز "
                    f"Verification باید رفع شود: {readiness_diagnostics[0]}"
                )
            else:
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
        self.store.set_setting(self._repair_attempts_setting_key(saved.project_id), 0)

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
        context_policy = (
            ContextPolicy(
                max_files_per_pack=4,
                max_bytes_per_file=8_192,
                max_total_bytes_per_pack=32_768,
                max_candidate_file_bytes=1_048_576,
                max_candidates=2_500,
            )
            if self.compact_retry
            else None
        )
        context = build_context_selection(
            task=task,
            project=self.detection,
            plan=plan,
            brain_index=self.brain_index,
            policy=context_policy,
        )
        budget = lock_token_budget(build_token_budget(plan=plan, selection=context, policy=policy_for_preset("economy")))
        graph = build_agent_run_graph(plan=plan, selection=context, budget=budget)
        return plan, context, budget, graph

    def _record_planning_failure(
        self,
        error: BaseException,
        *,
        task: ProductTask | None = None,
    ) -> None:
        """Keep plan-construction failures on the ticket screen.

        Planning happens before a persisted run exists.  Without this state
        transition a graph-construction exception only reaches the HTTP error
        banner, leaving the user with no repair action and no way to continue.
        Store the bounded task and an actionable failure context instead; the
        request handler may still return 400, but the next refresh is a usable
        recovery screen rather than an unowned error page.
        """

        message = safe_user_error(error, language=self.language)
        with self.lock:
            if task is not None:
                self.task = task
                self.active_task_id = task.task_id
            self.phase = "task"
            self.plan = None
            self.context = None
            self.budget = None
            self.graph = None
            self.benchmark = None
            self.run = None
            self.verification = None
            self.review = None
            self.export = None
            self.node_states.clear()
            self.error = message
            self.message_level = "error"
            self.message = message
        self._capture_failure_context()

    def select_task(self, task_id: str, *, restore: bool = False) -> None:
        if self.running:
            raise RuntimeError("Stop the active run before switching tickets.")
        if self.active_project_id is None or self.detection is None:
            raise RuntimeError("Choose a project first.")
        saved = self.store.get_task(task_id)
        if saved.project_id != self.active_project_id:
            raise ValueError("task does not belong to the selected project")
        task = self._task_from_contract(saved)
        self.budget_preset = "economy"
        try:
            plan, context, budget, graph = self._materialize_workflow(task)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._record_planning_failure(exc, task=task)
            raise
        releases = self.store.list_task_releases(task.task_id)
        latest_release = releases[0] if releases else None
        release_manifest = (
            self._load_release_manifest(Path(latest_release.manifest_path))
            if latest_release is not None
            else None
        )
        restored_delta = (
            latest_release is not None
            and release_manifest is not None
            and release_manifest.get("archive_mode") == "delta"
        )
        release_metadata: dict[str, Any] = release_manifest or {}
        restore_error: str | None = None
        # v3 releases contain a complete integrity contract.  Validate all
        # three artifacts before presenting one as verified after a restart.
        # Older development records had only display metadata; keep those
        # readable for migration while never weakening validation for a v3
        # archive produced by the current exporter.
        if latest_release is not None and release_manifest is not None and release_manifest.get("schema_version") == 3:
            try:
                release_metadata = validate_export_artifacts(
                    latest_release.archive_path,
                    latest_release.manifest_path,
                    latest_release.checksum_path,
                    expected_sha256=latest_release.sha256,
                    expected_file_count=latest_release.file_count,
                    expected_changed_files=release_manifest.get("changed_files", ()),
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                restored_delta = False
                restore_error = f"Saved release could not be verified and was not restored: {exc}"
        changed_files = (
            tuple(str(item) for item in release_metadata.get("changed_files", []))
            if restored_delta
            else ()
        )
        deleted_files = (
            tuple(str(item) for item in release_metadata.get("deleted_files", []))
            if restored_delta
            else ()
        )
        restored_export = (
            ExportedProject(
                project_root=self.detection.descriptor.root,
                archive_path=Path(latest_release.archive_path),
                manifest_path=Path(latest_release.manifest_path),
                checksum_path=Path(latest_release.checksum_path),
                sha256=latest_release.sha256,
                file_count=latest_release.file_count,
                verified=latest_release.verified,
                archive_mode="delta",
                changed_files=changed_files,
                deleted_files=deleted_files,
                baseline_sha256=(
                    str(release_metadata.get("baseline_snapshot_sha256"))
                    if restored_delta and release_metadata.get("baseline_snapshot_sha256")
                    else None
                ),
                extraction_root=(
                    str(release_metadata.get("extraction_root"))
                    if restored_delta and release_metadata.get("extraction_root")
                    else self.detection.descriptor.root.name
                ),
            )
            if latest_release is not None and restored_delta
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
            if self.recovery.task_id != task.task_id:
                stored_recovery = self.store.get_setting(f"recovery-task.v1.{task.task_id}")
                self.recovery = RecoveryState.from_dict(stored_recovery) if stored_recovery else RecoveryState(policy=self.recovery.policy, original_request=saved.request_text, task_id=task.task_id)
            if self.recovery.status == "running":
                self.recovery.stop("interrupted: Inspect the saved checkpoint and explicitly resume.")
            self.repair_attempts = self.recovery.attempts
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = restore_error
            if restore_error is not None:
                self.message_level = "warning"
                self.message = restore_error
            elif latest_release is not None and not restored_delta:
                self.message = (
                    "خروجی قدیمی کامل بود؛ برای جلوگیری از تحویل ناقص، ZIP تغییرات را دوباره تولید کنید."
                )
            elif restore:
                self.message = "تیکت قبلی بازیابی شد."
            else:
                self.message = "تیکت انتخاب شد."
        # A successful task selection starts from that task's own artifacts;
        # do not carry a planning failure from a different ticket into it.
        self._clear_failure_context()
        self.store.set_setting("active_task_id", task.task_id)
        self._restore_task_artifacts(task.task_id)
        self._save_recovery()

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
        if restored_verification is not None and restored_verification.finalize_allowed:
            self._resolve_failure_memory_after_verification(restored_verification)
        else:
            self._capture_failure_context()

    def _failure_context_from_state(self) -> dict[str, Any] | None:
        """Build a bounded, redacted incident record from the current run."""

        roots = (
            self.detection.descriptor.root
            if self.detection is not None
            else self.workspace_root,
            self.workspace_root,
        )
        diagnostics: list[str] = []
        failures: list[dict[str, Any]] = []
        evidence = ""
        kind = "check_failed"
        if self.verification is not None:
            evidence = self._workspace_reference(self.verification.evidence_path)
            diagnostics = [
                _safe_verification_detail(item, roots)
                for item in self.verification.diagnostics
                if item.strip()
            ]
            for result in self.verification.results:
                if result.status != "fail":
                    continue
                detail = _safe_verification_detail(
                    result.stderr.strip() or result.stdout.strip(),
                    roots,
                )
                detail, inferred_kind = _add_entrypoint_hint(detail, self.detection)
                failures.append(
                    {
                        "label": result.check.label,
                        "category": result.check.category,
                        "returncode": result.returncode,
                        "detail": detail,
                        "kind": inferred_kind or _failure_kind(detail),
                    }
                )
            existing_details = {str(item.get("detail", "")) for item in failures}
            for diagnostic in diagnostics:
                if diagnostic in existing_details:
                    continue
                failures.append(
                    {
                        "label": "Verification configuration",
                        "category": "configuration",
                        "returncode": None,
                        "detail": diagnostic,
                        "kind": _failure_kind(diagnostic),
                    }
                )
            if diagnostics or failures or self.verification.status != "pass":
                kind = "verification_failed"
        if self.run is not None and self.run.status != "completed":
            message = _safe_verification_detail(
                self.run.error_message or "The Agent run ended without a complete result.",
                roots,
            )
            # A graph-level error can be deliberately generic (for example,
            # ``objective_not_met``).  Recover the bounded worker report so
            # the user sees the actual blocker, such as a target outside the
            # node's ownership, instead of an opaque summary.  Evidence is
            # read only from Empy's own run directory and is redacted before
            # it reaches the browser.
            agent_reports: list[str] = []
            for node in self.run.node_results:
                if node.status not in {"failed", "cancelled", "timed_out", "unavailable"}:
                    continue
                final_path = Path(node.final_message_path)
                try:
                    if not final_path.is_absolute():
                        final_path = self.workspace_root / final_path
                    if not final_path.is_file() or not final_path.resolve().is_relative_to(
                        self.workspace_root.resolve()
                    ):
                        continue
                    report = _safe_verification_detail(
                        final_path.read_text(encoding="utf-8", errors="replace")[:2400],
                        roots,
                    )
                except (OSError, UnicodeError, RuntimeError):
                    continue
                if report:
                    agent_reports.append(report[:2400])
            for report in agent_reports[:2]:
                if report.casefold() not in message.casefold():
                    message = f"{message} Agent report: {report}"
            if message not in diagnostics:
                diagnostics.append(message)
            failure_kind = _failure_kind(message)
            if self.run.error_code == "dirty_worktree":
                failure_kind = "dirty_worktree"
            elif self.run.error_code == "budget_exceeded":
                failure_kind = "token_budget"
            failures.append(
                {
                    "label": "Agent execution",
                    "category": "execution",
                    "returncode": None,
                    "detail": message,
                    "kind": failure_kind,
                }
            )
            kind = (
                failure_kind
                if failure_kind in {
                    "dirty_worktree",
                    "no_change",
                    "ownership_mismatch",
                    "no_writable_files",
                    "token_budget",
                }
                else "run_failed"
            )
        if not diagnostics and not failures and self.error:
            message = _safe_verification_detail(self.error, roots)
            diagnostics.append(message)
            failure_kind = _failure_kind(message)
            failures.append(
                {
                    "label": "Empy execution",
                    "category": "execution",
                    "returncode": None,
                    "detail": message,
                    "kind": failure_kind,
                }
            )
            kind = failure_kind if failure_kind in {
                "dirty_worktree",
                "token_budget",
                "no_writable_files",
                "no_change",
            } else "run_failed"
        if not diagnostics and not failures:
            return None
        unique_diagnostics = list(dict.fromkeys(diagnostics))[:8]
        unique_failures: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for failure in failures:
            marker = (str(failure.get("label", "")), str(failure.get("detail", "")))
            if marker in seen:
                continue
            seen.add(marker)
            unique_failures.append(failure)
        return {
            "kind": kind,
            "diagnostics": unique_diagnostics,
            "failures": unique_failures[:8],
            "evidence": evidence,
            "created_at": _now(),
        }

    def _capture_failure_context(self) -> None:
        """Persist the last actionable failure so returning to a ticket is not a reset."""

        context = self._failure_context_from_state()
        with self.lock:
            self.failure_context = context
            project_id = self.active_project_id
        if project_id is not None:
            self.store.set_setting(self._failure_context_setting_key(project_id), context)
        if context is not None:
            self._failure_memory_record_from_context(context)
        self._refresh_failure_memory_view()

    def _clear_failure_context(self) -> None:
        with self.lock:
            self.failure_context = None
            project_id = self.active_project_id
            self.repair_attempts = 0
        if project_id is not None:
            self.store.set_setting(self._failure_context_setting_key(project_id), None)
            self.store.set_setting(self._repair_attempts_setting_key(project_id), 0)
        self._refresh_failure_memory_view()

    def _localized_failure_context(self) -> dict[str, Any] | None:
        raw = self.failure_context
        if self.run is not None and self.run.status != "completed":
            # Rebuild a failed-run context on every read.  Persisted contexts
            # can predate an agent's final evidence, and keeping that stale
            # snapshot would continue to show only the generic graph error.
            refreshed = self._failure_context_from_state()
            if refreshed is not None:
                raw = refreshed
        elif raw is None and (
            (self.verification is not None and self.verification.status != "pass")
            or (self.run is not None and self.run.status != "completed")
            or self.error
        ):
            raw = self._failure_context_from_state()
        if raw is None:
            return None
        failures = raw.get("failures", [])
        diagnostics = raw.get("diagnostics", [])
        first_kind = str(failures[0].get("kind", "")) if failures else ""
        if self.language == "en":
            title = "Why the previous run stopped"
            summary = (
                "Empy found a concrete problem in the project or its verification contract. "
                "The original project is safe; the isolated copy needs one repair pass."
            )
            next_step = (
                "Choose automatic repair. Empy will change only the isolated copy, rerun the checks, "
                "and keep ZIP disabled until the result is real."
            )
            suggested_prefix = "Resolve the previous failure at its root, not by changing the ticket text."
            action_map = {
                "no_change": "Check whether the requested state is already present. If it is, emit the required EMPY_NODE_RESULT: PASS attestation and let deterministic Verification decide; otherwise modify the owned file.",
                "no_writable_files": "Rebuild the bounded project index and assign the implementation role a real writable source file or an explicitly approved missing target; do not stop at a read-only plan.",
                "ownership_mismatch": "Refresh the project index and map the node to the real entry point or asset. Do not widen ownership to unrelated files or create a placeholder just to make the run pass.",
                "missing_dependency": "Install the missing project dependency in the isolated copy, or add an explicit safe verification manifest. Do not silently skip the required check.",
                "missing_verification_contract": "Add or repair the project's explicit .empy/verification.json contract, or provide a supported test/build/lint entry point.",
                "missing_file_or_route": "Inspect whether the reported file or route is truly required. If the check is inconsistent with the project's real entry point, fix the check contract; do not create a placeholder only to make it pass.",
                "verification_contract_mismatch": "The check expects a different entry point or layout than the detected project. Repair the verification/site-audit contract or the approved product requirement; do not create a placeholder file only to make the check green.",
                "permission": "Choose an accessible project copy or repair the isolated workspace permissions, then rerun the same check.",
                "dirty_worktree": "The previous attempt left unreviewed changes in Empy's isolated copy. Preserve that attempt, reset only the isolated copy to its last accepted baseline, and continue the ticket; the original project is not changed.",
                "timeout": "Reduce the check scope or repair the hanging command, then rerun it with bounded output.",
                "token_budget": "The agent reached Empy's safe fresh-token limit. Retry the same change with a compact context; do not expand the ticket or repeat discovery.",
                "check_failed": "Fix the exact issue reported by this check in the isolated project, then rerun Verification.",
            }
        else:
            title = "علت واضح توقف کار"
            summary = (
                "Empy یک مشکل واقعی پیدا کرده است. فایل اصلی شما تغییر نکرده؛ "
                "اصلاح باید فقط در کپی ایزوله انجام شود."
            )
            next_step = (
                "روی «اصلاح خودکار» بزنید؛ Empy خودش فایل مناسب را اصلاح می‌کند، "
                "دوباره تست می‌گیرد و فقط در صورت موفقیت ZIP می‌سازد."
            )
            suggested_prefix = "علت خطای قبلی را ریشه‌ای اصلاح کن، نه اینکه فقط متن تیکت را عوض کنی."
            action_map = {
                "no_change": "بررسی کن آیا وضعیت درخواستی از قبل وجود دارد یا نه. اگر وجود دارد، گزارش صریح EMPY_NODE_RESULT: PASS بده تا Verification قطعی آن را تأیید کند؛ در غیر این صورت فایلِ مالکیت‌داده‌شده را واقعاً اصلاح کن.",
                "no_writable_files": "فهرست محدود پروژه را دوباره بساز و نقش اجرایی را به یک فایل واقعیِ قابل‌ویرایش یا هدف جدیدِ صریحاً تأییدشده وصل کن؛ برنامهٔ فقط‌خواندنی نساز.",
                "ownership_mismatch": "فهرست پروژه را تازه کن و نود را به ورودی یا فایل واقعی همان پروژه وصل کن؛ دامنهٔ مالکیت را برای سبزکردن اجرا به فایل‌های نامرتبط گسترش نده و فایل صوری نساز.",
                "missing_dependency": "وابستگی گمشده را در کپی ایزوله نصب/تأمین کن یا یک قرارداد بررسی امن در .empy/verification.json تعریف کن؛ تست لازم نباید بی‌صدا رد شود.",
                "missing_verification_contract": "قرارداد .empy/verification.json یا ورودی تست/build/lint پشتیبانی‌شده را اصلاح کن تا Verification دقیقاً بداند چه چیزی را باید اجرا کند.",
                "missing_file_or_route": "بررسی کن فایل یا مسیر گزارش‌شده واقعاً برای پروژه لازم است یا تست با ورودی واقعی پروژه ناسازگار است. قرارداد تست را اصلاح کن؛ فقط برای سبزکردن تست فایل صوری نساز.",
                "verification_contract_mismatch": "تست با ورودی یا ساختار واقعی پروژه سازگار نیست؛ قرارداد Verification/site-audit یا نیازمندی محصول را اصلاح کن و فقط برای سبزشدن تست فایل جعلی نساز.",
                "permission": "کپی ایزولهٔ قابل‌دسترسی را انتخاب یا دسترسی همان workspace را اصلاح کن و همان بررسی را دوباره اجرا کن.",
                "dirty_worktree": "تلاش قبلی در کپی ایزوله تغییر تأییدنشده باقی گذاشته است؛ Empy آن را در همان workspace نگه می‌دارد، فقط کپی ایزوله را به آخرین مبنای تأییدشده برمی‌گرداند و تیکت را ادامه می‌دهد. فایل اصلی پروژه تغییر نمی‌کند.",
                "timeout": "فرمان متوقف‌شده را محدود یا اصلاح کن و Verification را دوباره با خروجی کنترل‌شده اجرا کن.",
                "token_budget": "سقف مصرف توکن این مرحله پر شد؛ همان تغییر را با context کوچک‌تر دوباره اجرا کن و تیکت را بزرگ‌تر یا تکراری نکن.",
                "check_failed": "ایراد دقیق گزارش‌شده توسط همین بررسی را در پروژهٔ ایزوله اصلاح کن و سپس Verification را دوباره اجرا کن.",
            }
        if first_kind == "token_budget":
            if self.language == "en":
                title = "This step used too many tokens"
                summary = "Empy stopped this step before a complete result was produced. No ZIP is ready."
                next_step = (
                    "Choose automatic repair. Empy will retry the same change with a compact context "
                    "and will not repeat discovery."
                )
            else:
                title = "مصرف توکن این مرحله بیش از حد شد"
                summary = "Empy این مرحله را قبل از تولید نتیجهٔ کامل متوقف کرد؛ هنوز ZIP آماده نیست."
                next_step = "روی «اصلاح خودکار» بزنید؛ همان تغییر با context کوچک‌تر و بدون discovery تکراری اجرا می‌شود."
        if first_kind == "no_writable_files":
            if self.language == "en":
                title = "The ticket was not connected to a writable file"
                summary = (
                    "Empy found an implementation role but its bounded project index did not assign a safe writable target. "
                    "No project file was changed."
                )
                next_step = (
                    "Choose Automatically repair and rerun. Empy will refresh the project index, select the real source file, "
                    "or create the approved missing target before it starts an Agent."
                )
            else:
                title = "تیکت به فایل قابل‌ویرایش وصل نشد"
                summary = (
                    "Empy برای نقش اجرایی فایل امن و قابل‌ویرایش پیدا نکرد؛ هیچ فایل پروژه تغییر نکرده است. "
                    "مسیر انتخاب فایل باید اصلاح شود."
                )
                next_step = (
                    "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy فهرست پروژه را تازه می‌کند، فایل واقعی را انتخاب می‌کند "
                    "یا هدفِ مجازِ فایل جدید را قبل از شروع Agent می‌سازد."
                )
        if first_kind == "no_change":
            if self.language == "en":
                title = "The Agent made no change without a verifiable PASS"
                summary = (
                    "The Agent did not change a project file and did not provide the required "
                    "PASS attestation, so Empy could not safely continue to Verification."
                )
                next_step = (
                    "Choose Automatically repair and rerun. Empy will verify whether the "
                    "requested state already exists or make the bounded change."
                )
            else:
                title = "Agent بدون تأیید PASS تغییری ایجاد نکرد"
                summary = (
                    "Agent هیچ فایل پروژه را تغییر نداد و تأیید صریح PASS ارائه نکرد؛ "
                    "برای ادامهٔ امن، Verification متوقف شد."
                )
                next_step = (
                    "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy بررسی می‌کند وضعیت درخواستی "
                    "از قبل وجود دارد یا تغییر محدود لازم است."
                )
        if first_kind == "ownership_mismatch":
            if self.language == "en":
                title = "The selected file target does not match this project"
                summary = (
                    "Empy found the requested work, but the node was assigned a file that is not the project's real entry point or asset. "
                    "No unapproved file was changed."
                )
                next_step = (
                    "Choose Automatically repair and rerun. Empy will refresh the project map and assign the real target before using another Agent."
                    if self.repair_attempts < self.recovery.policy.max_attempts
                    else "Continue and fix the ticket after selecting the real project target."
                )
            else:
                title = "هدف فایل با ساختار واقعی پروژه یکی نیست"
                summary = (
                    "Empy فایل لازم را در محدودهٔ واقعی پروژه پیدا نکرد؛ نود اجازهٔ تغییر فایل درست را نداشت و هیچ تغییر تأییدنشده‌ای ثبت نشد."
                )
                next_step = (
                    "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy فهرست پروژه را تازه می‌کند و قبل از مصرف دوباره، فایل واقعی را به نود می‌دهد."
                    if self.repair_attempts < self.recovery.policy.max_attempts
                    else "ابتدا هدف واقعی پروژه را مشخص کنید و سپس «ادامه و اصلاح تیکت» را بزنید."
                )
        if first_kind == "dirty_worktree":
            if self.language == "en":
                title = "The previous attempt needs a safe retry"
                summary = (
                    "Empy stopped before starting the next Agent because the isolated project still contains changes from an earlier attempt. "
                    "Your original project is unchanged."
                )
                next_step = (
                    "Choose Safely reset and continue. Empy will keep the previous attempt inside the workspace, reset only the isolated copy to its last accepted baseline, and retry the ticket."
                )
            else:
                title = "تلاش قبلی نیاز به ادامهٔ امن دارد"
                summary = (
                    "Empy قبل از شروع Agent بعدی متوقف شد چون کپی ایزوله هنوز تغییرات تلاش قبلی را دارد. "
                    "فایل اصلی پروژهٔ شما تغییر نکرده است."
                )
                next_step = (
                    "روی «پاک‌سازی امن و ادامه» بزنید؛ Empy تلاش قبلی را داخل workspace نگه می‌دارد، فقط کپی ایزوله را به آخرین مبنای تأییدشده برمی‌گرداند و تیکت را دوباره اجرا می‌کند."
                )
        findings = list(dict.fromkeys(str(item) for item in diagnostics if str(item).strip()))
        rendered_failures: list[dict[str, Any]] = []
        ticket_lines = [suggested_prefix]
        for item in failures:
            label = str(item.get("label", "Verification check"))
            detail = str(item.get("detail", "No diagnostic output was produced."))
            item_kind = str(item.get("kind", "check_failed"))
            rendered_failures.append(
                {
                    "label": label,
                    "category": str(item.get("category", "")),
                    "kind": item_kind,
                    "returncode": item.get("returncode"),
                    "detail": detail,
                    "user_finding": _plain_failure_finding(
                        item_kind,
                        detail,
                        language=self.language,
                    ),
                    "action": action_map.get(item_kind, action_map["check_failed"]),
                }
            )
            findings.append(f"{label}: {detail}")
            ticket_lines.append(f"- {label}: {detail}")
            ticket_lines.append(f"- Required action: {action_map.get(item_kind, action_map['check_failed'])}")
        if not rendered_failures and findings:
            ticket_lines.extend(f"- Finding: {item}" for item in findings)
        ticket_lines.append(
            "- After the correction, run the same verification checks again and report the real evidence; do not claim success if a check was skipped or failed."
            if self.language == "en"
            else "- بعد از اصلاح، همان بررسی‌ها را دوباره اجرا کن و evidence واقعی بده؛ اگر بررسی رد یا skip شد، موفق اعلام نکن."
        )
        return {
            "kind": (
                "token_budget"
                if first_kind == "token_budget"
                else raw.get("kind", "check_failed")
            ),
            "title": (
                "صفحهٔ اول ساخته نشد؛ نام فایل با تست یکی نیست"
                if self.language == "fa" and first_kind == "verification_contract_mismatch"
                else "The home page was not delivered because the file name does not match the check"
                if self.language == "en" and first_kind == "verification_contract_mismatch"
                else title
            ),
            "summary": (
                _plain_failure_finding(
                    first_kind,
                    str(failures[0].get("detail", "")),
                    language=self.language,
                )
                if failures and first_kind == "verification_contract_mismatch"
                else summary
            ),
            "next_step": next_step,
            "findings": list(dict.fromkeys(findings))[:12],
            "failures": rendered_failures,
            "evidence": raw.get("evidence", ""),
            "suggested_ticket": "\n".join(ticket_lines)[:4000],
            "repair_available": self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running",
            "repair_attempts": self.repair_attempts,
        }

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
                    f"- {result.check.check_id}: {result.check.label}; command={list(result.check.command)!r} (return code {result.returncode}): {detail}"
                )
            return "\n".join(lines)[:4000]
        failure_context = (
            self._failure_context_from_state()
            if self.run is not None and self.run.status != "completed"
            else self.failure_context
        )
        if failure_context is not None:
            lines = [
                "Previous Empy execution failed and the next attempt must resolve its confirmed root cause before release:",
            ]
            failures = failure_context.get("failures", [])
            if failures:
                for item in failures[:4]:
                    label = str(item.get("label", "Agent execution"))
                    detail = _safe_verification_detail(str(item.get("detail", "")), roots)
                    lines.append(f"- {label}: {detail}")
            else:
                lines.extend(
                    f"- {item}"
                    for item in failure_context.get("diagnostics", [])[:4]
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
        self._prepare_clean_worktree_for_run()
        self._capture_failure_context()
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
            self.dependency_bootstrap = None
            self.node_states.clear()
            self.phase = "task"
            self.error = None
            self.message = "یافته‌های شکست قبلی حفظ شد؛ تیکت اصلاحی را وارد کنید."
        self.store.set_setting("active_task_id", None)

    def _save_recovery(self) -> None:
        if self.recovery.task_id:
            self.store.set_setting(f"recovery-task.v1.{self.recovery.task_id}", self.recovery.to_dict())
        if self.active_project_id is not None:
            self.store.set_setting(f"recovery.v1.{self.active_project_id}", self.recovery.to_dict())
            self.store.set_setting(self._repair_attempts_setting_key(self.active_project_id), self.repair_attempts)

    def set_recovery_policy(self, policy: dict[str, Any]) -> None:
        if self.running or self.recovery.started_at is not None:
            raise RuntimeError("Recovery policy is locked for this workflow; create a new ticket to change its bounds.")
        self.recovery.policy = RecoveryPolicy(**policy)
        self._save_recovery()

    def _account_recovery_usage(self) -> None:
        if self.run is not None:
            usage = self.run.usage
            known = usage is not None and usage.source == "provider"
            # A partially observed graph is not a fully measured run.
            complete = known and all(node.usage is not None and node.usage.source == "provider" for node in self.run.node_results if node.status != "skipped")
            self.recovery.account(
                self.run.run_id,
                usage.uncached_total if known and usage is not None else None,
                self.budget.total_limit_tokens if self.budget is not None else self.recovery.policy.max_fresh_tokens,
                complete=complete,
            )
            self._save_recovery()

    def _stop_recovery(self, reason: str) -> None:
        self.recovery.stop(reason)
        self._save_recovery()
        self.add_log(reason, "warning")

    def _cancel_recovery_deadline(self) -> None:
        if self.recovery_deadline is not None:
            self.recovery_deadline.cancel()
            self.recovery_deadline = None

    def _recovery_checkpoint(self) -> str:
        if self.detection is None:
            return "unknown"
        root = self.detection.descriptor.root
        snapshot = CodexGraphRuntime._git_snapshot(root)
        digest = hashlib.sha256()
        if snapshot is not None:
            for path in sorted(snapshot.status):
                digest.update(path.encode())
                target = root / path
                if target.is_file() and not target.is_symlink():
                    digest.update(hashlib.sha256(target.read_bytes()).digest())
        return digest.hexdigest()

    def auto_repair(self, *, automatic: bool = False) -> None:
        """Run a bounded correction using durable evidence and the original scope."""
        if self.detection is None or self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        if self.running or self.recovery.status == "running":
            raise RuntimeError("A recovery attempt is already active.")
        if automatic and self.recovery.stop_reason is not None:
            return
        if self.verification is not None and self.verification.finalize_allowed:
            raise RuntimeError("Verification already passed; review the result.")
        if self.run is not None and self.run.status == "cancelled" and automatic:
            self._stop_recovery("cancelled: The user stopped this workflow.")
            return
        if self.run is not None and self.run.error_code == "scope_violation":
            scope_reason = "scope_violation: Review unowned changes before any corrective execution."
            self._stop_recovery(scope_reason)
            raise RuntimeError(scope_reason)
        self._account_recovery_usage()
        reason = self.recovery.limit_reason()
        if reason:
            self._stop_recovery(reason)
            raise RuntimeError(reason)
        context = self._build_continuation_context()
        blocker = external_block(context)
        if blocker:
            blocker = f"{blocker} Details: {context[:1800]}"
            self._stop_recovery(blocker)
            raise RuntimeError(blocker)
        if not self.recovery.original_request:
            saved = self.store.get_task(self.active_task_id) if self.active_task_id else None
            self.recovery.original_request = saved.request_text if saved else (self.task.objective if self.task else "Complete the requested project work.")
        original_request = self.recovery.original_request
        self.recovery.task_id = self.active_task_id
        owner = next((node.agent_role for node in self.graph.nodes if node.agent_role != "quality"), "quality") if self.graph else "quality"
        # Record each terminal outcome once, including explicit retries of a stopped workflow.
        if not self.recovery.history or self.recovery.history[-1]["cycle"] != self.recovery.attempts:
            no_progress = self.recovery.record_failure(context, self._recovery_checkpoint(), owner)
            self._save_recovery()
            if no_progress and automatic:
                self._stop_recovery(no_progress)
                return
        strategy = "Inspect the failing contract and root cause; do not repeat the previous patch." if self.recovery.history[-1]["progress"] == "unchanged_failure" else "Fix only the confirmed failure."
        self._prepare_clean_worktree_for_run()
        self.continuation_context = (
            f"Recovery owner: {owner}. {strategy}\n"
            "Preserve previous fixes and checkpoints. Do not repeat discovery or unrelated analysis. "
            "Remain within the original request and approved ownership. Empy runs the real verification after this correction.\n"
            f"علت قطعی شکست قبلی / Exact failing checks:\n{context}"
        )[:5000]
        self.compact_retry = _failure_kind(context) == "token_budget"
        self.recovery.begin()
        self.repair_attempts = self.recovery.attempts
        self._save_recovery()  # Reserve the cycle before any work; restart never replays it.
        try:
            self.create_plan(original_request, task_id=self.active_task_id)
            reason = self.recovery.limit_reason(planned_tokens=self.budget.total_limit_tokens if self.budget else 0, check_attempts=False)
            # The cycle just reserved is allowed even when it consumes the final slot.
            if reason:
                raise RuntimeError(reason)
            self.add_log(f"Recovery cycle {self.repair_attempts}/{self.recovery.policy.max_attempts}: {owner}.")
            self.start_run()
        except (OSError, RuntimeError, ValueError) as exc:
            self._stop_recovery(str(exc))
            raise

    def _maybe_start_automatic_repair(self, *, reason: str) -> None:
        if self.active_project_id is None or self.detection is None:
            return
        if self.recovery.stop_reason is not None:
            return
        self.recovery.status = "ready"
        self.add_log(f"{reason}; evaluating bounded recovery.", "warning")
        try:
            self.auto_repair(automatic=True)
        except (OSError, RuntimeError, ValueError) as exc:
            self.add_log(f"Automatic repair stopped: {exc}", "error")
            with self.lock:
                self.error = str(exc)
            self._capture_failure_context()

    def create_plan(self, raw_tasks: str, task_id: str | None = None, *, budget_preset: str | None = None) -> None:
        if self.detection is None or self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        if self.running:
            raise RuntimeError("Stop the active run before editing its plan.")
        if task_id is not None and self.recovery.task_id == task_id and self.recovery.started_at is not None and self.continuation_context is None:
            raise RuntimeError("Only draft tickets can be edited; create a new ticket for a changed objective.")
        if task_id is not None and self.store.get_task(task_id).project_id != self.active_project_id:
            raise ValueError("task does not belong to the selected project")
        # Retain the argument for older clients, but never increase the fixed policy.
        self.budget_preset = "economy"
        raw = raw_tasks.strip()
        if not raw:
            raise ValueError("Enter at least one task.")
        requirements, user_constraints = _split_task_lines(raw)
        if not requirements:
            raise ValueError("Enter at least one actionable task.")
        continuation_context = self.continuation_context
        if continuation_context is None:
            with self.lock:
                self.repair_attempts = 0
                self.compact_retry = False
                self.recovery = RecoveryState(policy=self.recovery.policy, original_request=raw)
            self.store.set_setting(
                self._repair_attempts_setting_key(self.active_project_id),
                0,
            )
        objective_requirements = list(requirements)
        task = build_product_task(
            task_id=task_id or uuid.uuid4().hex,
            project_root=str(self.detection.descriptor.root),
            kind="custom",
            title=requirements[0][:96],
            objective="\n".join(objective_requirements),
            requirements_text="\n".join(objective_requirements),
            constraints_text="\n".join((DEFAULT_CONSTRAINTS, *user_constraints, *((continuation_context,) if continuation_context else ()))),
            definition_of_done_text=DEFAULT_DEFINITION_OF_DONE,
        )
        ready = mark_ready_for_planning(task)
        try:
            plan, context, budget, graph = self._materialize_workflow(ready)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._record_planning_failure(exc, task=ready)
            raise
        # The ledger is consulted after the new graph is materialized so the
        # target/snapshot identity reflects this ticket rather than a stale
        # previous plan.  A related old incident becomes a compact handoff;
        # an exact unchanged incident is enforced at the provider gate below.
        self._refresh_failure_memory_view(task=ready, graph=graph, context=context)
        if self.failure_memory_hint and not self.failure_memory_blocked:
            ready = replace(
                ready,
                constraints=tuple(
                    dict.fromkeys((*ready.constraints, self.failure_memory_hint))
                ),
            )
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
            self.dependency_bootstrap = None
            self.node_states = {node.node_id: "waiting" for node in graph.nodes}
            self.phase = "plan"
            self.error = None
            self.continuation_context = None
            self.failure_context = None
            self.message = "برنامه و مالکیت فایل‌ها آماده شد."
        self.store.set_setting(f"budget-preset.v1.{self.active_project_id}", self.budget_preset)
        self.recovery.task_id = ready.task_id
        self._save_recovery()
        self.store.set_setting("active_task_id", ready.task_id)
        if self.active_project_id is not None:
            self.store.set_setting(self._failure_context_setting_key(self.active_project_id), None)
        self._refresh_failure_memory_view()

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

    def _prepare_clean_worktree_for_run(self) -> tuple[str, ...]:
        """Checkpoint safe partial work so a corrective run can build on it.

        Stashing the previous attempt made every repair rediscover and rewrite
        the same files.  Empy now creates a temporary local checkpoint in its
        isolated Git repository, runs the next Agent from a clean tree, then
        resets to the pre-checkpoint revision before Review so the user still
        sees and approves the complete cumulative diff.  The immutable import
        baseline and the user's original project are never changed.
        """

        if self.detection is None:
            return ()
        root = self.detection.descriptor.root
        snapshot = CodexGraphRuntime._git_snapshot(root)
        if snapshot is None or not snapshot.status:
            return ()

        paths = tuple(sorted(snapshot.status))
        unsafe: list[str] = []
        for path in paths:
            try:
                normalized = normalize_relative_path(path)
                if is_agent_denied_relative_path(normalized):
                    raise ValueError("generated or protected path")
                # Checkpointing is an isolated-worktree operation.  It needs
                # to preserve any safe user file, while provider ownership
                # remains intentionally narrower and never uses ``./``.
                project_path(root, normalized, allow_directory=False)
            except ValueError:
                unsafe.append(path)
        unsafe_paths = tuple(unsafe)
        if unsafe_paths:
            raise RuntimeError(
                "Empy found a protected or generated path in the isolated partial "
                "attempt and will not carry it into a repair: "
                + ", ".join(unsafe_paths)
            )
        recovery_root = (
            self.workspace_root
            / "recovery"
            / f"dirty-attempt-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        recovery_root.mkdir(parents=True, exist_ok=False)
        (recovery_root / "manifest.json").write_text(
            json.dumps(
                {
                    "kind": "isolated_dirty_worktree",
                    "project_relative_paths": list(paths),
                    "action": "local_carry_forward_checkpoint",
                    "source": "isolated_workspace_only",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        head_result = subprocess.run(
            ("git", "rev-parse", "--verify", "HEAD"),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if head_result.returncode != 0:
            detail = head_result.stderr.strip() or "Git baseline is unavailable"
            raise RuntimeError(
                "Empy could not identify the isolated review baseline; "
                f"no new run was started. {detail}"
            )
        if self.carry_forward_base_revision is None:
            self.carry_forward_base_revision = head_result.stdout.strip()
            if self.active_project_id is not None:
                self.store.set_setting(
                    self._carry_forward_setting_key(self.active_project_id),
                    self.carry_forward_base_revision,
                )
        checkpoint_accepted_changes(root, paths)
        remaining = CodexGraphRuntime._git_snapshot(root)
        if remaining is not None and remaining.status:
            raise RuntimeError(
                "Empy checkpointed the previous isolated changes, but the workspace "
                "is still not clean; no new run was started. Re-import the project copy."
            )
        self.add_log(
            f"Empy carried {len(paths)} safe partial change(s) into the corrective run.",
            "warning",
        )
        return paths

    def _restore_carry_forward_review_base(self, root: Path) -> None:
        base = self.carry_forward_base_revision
        if base is None and self.active_project_id is not None:
            saved = self.store.get_setting(
                self._carry_forward_setting_key(self.active_project_id)
            )
            base = saved if isinstance(saved, str) and saved else None
        if base is None:
            return
        result = subprocess.run(
            ("git", "reset", "--mixed", base),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "git reset failed"
            raise RuntimeError(
                "Empy completed the corrective Agent but could not restore the cumulative "
                f"Review diff. {detail}"
            )
        self.carry_forward_base_revision = None
        if self.active_project_id is not None:
            self.store.set_setting(
                self._carry_forward_setting_key(self.active_project_id),
                None,
            )

    def start_run(self) -> None:
        with self.lock:
            if self.running or self._starting_run:
                raise RuntimeError("A run is already active or starting.")
            self._starting_run = True
        try:
            self._start_run()
        finally:
            with self.lock:
                self._starting_run = False

    def _start_run(self) -> None:
        if self.route_settings_error:
            raise RuntimeError(self.route_settings_error)
        if self.running:
            raise RuntimeError("A run is already active.")
        if self.graph is None or self.context is None or self.budget is None or self.detection is None:
            raise RuntimeError("Build a plan first.")
        reason = self.recovery.limit_reason(planned_tokens=self.budget.total_limit_tokens, check_attempts=False)
        if reason:
            self._stop_recovery(reason)
            raise RuntimeError(reason)
        # Verification readiness is a hard gate before even inspecting or
        # invoking a provider for missing dependencies or an invalid contract.
        # Static web findings are different: a requested frontend repair may
        # be precisely what fixes the broken reference.  Keep those findings
        # in the final full-project Verification, but do not deadlock the
        # bounded Agent before it can repair the selected file.
        static_scope = tuple(
            sorted(
                {
                    item.relative_path
                    for pack in self.context.packs
                    for item in pack.files
                }
            )
        )
        preflight = verification_preflight(
            self.detection,
            static_scope=static_scope or None,
        )
        # A project can legitimately need both Composer and Node.  Prepare at
        # most one bounded, lockfile-backed dependency set per pass, then
        # re-read the contract before allowing the provider inspection.  Any
        # non-static diagnostic remains a hard stop and costs no tokens.
        for _ in range(3):
            blocking_diagnostics = tuple(
                item
                for item in preflight.diagnostics
                if not item.startswith("Static web validation failed:")
            )
            dependency_only = bool(blocking_diagnostics) and all(
                "dependencies are not available in the isolated copy" in item
                for item in blocking_diagnostics
            )
            if preflight.checks and not blocking_diagnostics:
                if preflight.diagnostics:
                    with self.lock:
                        self.message = (
                            "Verification static web findings will be rechecked after the Agent run."
                        )
                        self.message_level = "warning"
                break
            if not dependency_only:
                detail = "; ".join(blocking_diagnostics or preflight.diagnostics)
                message = f"Verification preflight blocked the provider run: {detail}"
                with self.lock:
                    self.error = message
                    self.message_level = "warning"
                    self.message = message
                self._capture_failure_context()
                raise RuntimeError(message)
            self._prepare_dependencies(self.detection, None)
            preflight = verification_preflight(self.detection)
        blocking_diagnostics = tuple(
            item
            for item in preflight.diagnostics
            if not item.startswith("Static web validation failed:")
        )
        if not preflight.checks or blocking_diagnostics:
            detail = "; ".join(blocking_diagnostics or preflight.diagnostics)
            message = f"Verification preflight blocked the provider run: {detail}"
            with self.lock:
                self.error = message
                self.message_level = "warning"
                self.message = message
            self._capture_failure_context()
            raise RuntimeError(message)
        # Do this local, durable check immediately before provider inspection.
        # A matching open incident with the same target and content snapshot
        # is a redundant expensive run; a changed target/snapshot naturally
        # produces a different scope identity and remains eligible.
        self._refresh_failure_memory_view()
        if self.failure_memory_blocked and self.failure_memory_block_reason:
            with self.lock:
                self.error = self.failure_memory_block_reason
                self.message = self.failure_memory_block_reason
                self.message_level = "warning"
            raise RuntimeError(self.failure_memory_block_reason)
        installation = self.driver.inspect(refresh=True)
        if installation.availability != "available" or not installation.authenticated:
            detail = installation.remediation or installation.message
            self._stop_recovery("credentials: " + detail)
            with self.lock:
                self.error = detail
                self.message = detail
                self.message_level = "warning"
            self._capture_failure_context()
            raise RuntimeError(detail)
        if self.active_project_id is None or self.active_task_id is None:
            raise RuntimeError("Project and task identity are missing.")
        self._prepare_clean_worktree_for_run()
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
            self.message_level = "info"
            self.logs.clear()
        if self.recovery.started_at is None:
            self.recovery.started_at = time.time()
        self.recovery.status = "running"
        self.recovery.stop_reason = None
        self._save_recovery()

        def deadline() -> None:
            if self.runtime is not runtime:
                return
            self._stop_recovery("time_exhausted: Workflow time allowance exhausted; inspect preserved changes.")
            cancel_event.set()
            runtime.cancel()

        self.recovery_deadline = threading.Timer(self.recovery.remaining_seconds(), deadline)
        self.recovery_deadline.daemon = True
        self.recovery_deadline.start()
        thread = threading.Thread(target=self._run_worker, args=(run.run_id,), daemon=True, name="empy-web-run")
        thread.start()

    def _budget_result_can_continue_to_verification(
        self,
        result: CodexGraphExecution,
    ) -> bool:
        """Keep useful scoped changes instead of paying for a blind retry."""

        if result.error_code != "budget_exceeded" or self.graph is None:
            return False
        roles = {node.node_id: node.agent_role for node in self.graph.nodes}
        has_budget_limited_change = False
        for node in result.node_results:
            role = roles.get(node.node_id)
            if node.status == "completed":
                continue
            if node.status == "failed" and node.error_code == "budget_exceeded":
                if not node.changed_files or role not in {"frontend", "backend", "coordinator", "release"}:
                    return False
                has_budget_limited_change = True
                continue
            if node.status == "skipped" and role == "quality":
                continue
            return False
        return has_budget_limited_change

    def _promote_verified_budget_result(
        self,
        result: CodexGraphExecution,
    ) -> CodexGraphExecution:
        """Convert a locally verified budget-limited diff into a reviewable run."""

        if self.graph is None:
            raise RuntimeError("Agent graph is unavailable for budget recovery.")
        roles = {node.node_id: node.agent_role for node in self.graph.nodes}
        nodes = []
        for node in result.node_results:
            role = roles.get(node.node_id)
            if node.status == "failed" and node.error_code == "budget_exceeded":
                nodes.append(
                    replace(
                        node,
                        status="completed",
                        return_code=0,
                        summary=(
                            f"{node.summary}\n\nEmpy retained the scoped change after "
                            "deterministic Verification passed; provider budget was exceeded."
                        ),
                        error_code=None,
                        error_message=None,
                    )
                )
            elif node.status == "skipped" and role == "quality":
                nodes.append(
                    replace(
                        node,
                        status="completed",
                        return_code=0,
                        summary="Empy's deterministic Verification replaced this Provider quality node.",
                        error_code=None,
                        error_message=None,
                    )
                )
            else:
                nodes.append(node)
        promoted = replace(
            result,
            status="completed",
            node_results=tuple(nodes),
            error_code=None,
            error_message=None,
        )
        promoted.validate()
        return promoted

    def cancel_run(self) -> None:
        with self.lock:
            if not self.running or self.runtime is None:
                raise RuntimeError("There is no active run to cancel.")
            runtime = self.runtime
            cancel_event = self.cancel_event
            self.message = "درخواست توقف اجرا ثبت شد."
        self._stop_recovery("cancelled: The user stopped this workflow.")
        self._cancel_recovery_deadline()
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
        self.store.set_setting(f"run-route.v1.{result.run_id}", self.model_route.to_dict())
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
        self._cancel_recovery_deadline()
        self._account_recovery_usage()
        if state == "cancelled" and self.recovery.stop_reason is None:
            self._stop_recovery("cancelled: The user stopped this workflow.")
        elif self.recovery.status == "running":
            self.recovery.status = "ready"
            self._save_recovery()
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
        if state == "completed":
            self._clear_failure_context()
        else:
            self._capture_failure_context()

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
                cancel_event = self.cancel_event
            if runtime is None:
                raise RuntimeError("The run runtime was not initialized.")
            # Prepare real project dependencies before any provider call. This
            # keeps a missing vendor/node_modules directory from consuming
            # tokens and then surfacing as an avoidable verification failure.
            self._prepare_dependencies(detection, cancel_event)
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
            budget_recovery = self._budget_result_can_continue_to_verification(result)
            if result.status != "completed" and not budget_recovery:
                terminal_message = result.error_message or f"Codex run ended as {result.status}"
                terminal_state = "cancelled" if result.status == "cancelled" else "failed"
                self._record_terminal_result(
                    workspace_run_id,
                    result,
                    state=terminal_state,
                    message=terminal_message,
                    level="warning" if result.status == "cancelled" else "error",
                )
                if terminal_state == "failed" and result.error_code != "budget_exceeded":
                    self._maybe_start_automatic_repair(
                        reason="The Agent run ended before Verification"
                    )
                return
            if budget_recovery:
                self.add_log(
                    "The Provider budget was exceeded after a scoped file change; "
                    "Empy is verifying that preserved change locally before deciding on any retry.",
                    "warning",
                )
            self._restore_carry_forward_review_base(detection.descriptor.root)
            # The Agent may have changed a manifest or lockfile. Reconcile
            # dependencies once more in the same isolated copy before running
            # the final checks; never fabricate an autoloader or skip a check.
            self._prepare_dependencies(detection, cancel_event)
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
            if budget_recovery and not verification.finalize_allowed:
                message = (
                    "The budget-limited change was preserved but did not pass deterministic "
                    "Verification; only the exact failed check may be repaired."
                )
                self._record_terminal_result(
                    workspace_run_id,
                    result,
                    state="failed",
                    message=message,
                    level="error",
                    verification_id=verification.verification_id,
                    review_id=review.review_id,
                )
                self._maybe_start_automatic_repair(
                    reason="The preserved change failed deterministic Verification"
                )
                return
            # Keep the provider run status separate from project verification.
            # Agent execution may complete while a project check fails; marking
            # the whole run failed made the UI falsely blame the Agent phase.
            final_result = (
                self._promote_verified_budget_result(result)
                if budget_recovery
                else result
            )
            self.run = final_result
            self._cancel_recovery_deadline()
            self._account_recovery_usage()
            self.recovery.status = "verified" if verification.finalize_allowed else "ready"
            self._save_recovery()
            manifest_path = self._save_runtime_result(
                workspace_run_id,
                final_result,
                verification_id=verification.verification_id,
                review_id=review.review_id,
            )
            self.store.update_run(
                workspace_run_id,
                state="completed",
                summary=(
                    "Run and verification completed"
                    if verification.finalize_allowed
                    else "Run completed; verification failed"
                ),
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
                self.message_level = "success" if verification.finalize_allowed else "warning"
                self.error = None
            if verification.finalize_allowed:
                self._resolve_failure_memory_after_verification(verification)
                self._clear_failure_context()
            else:
                self._capture_failure_context()
                # A verification failure is an actionable finding, not a
                # terminal product state. Use the bounded repair path once
                # automatically so the user is not required to translate a
                # test failure into a second ticket by hand. The repair prompt
                # still forbids fake files and keeps every change isolated.
                self._maybe_start_automatic_repair(
                    reason="Verification found a real issue"
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
            self._maybe_start_automatic_repair(reason="Verification timed out")
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
            self._maybe_start_automatic_repair(
                reason="The Agent/verification process failed before producing a complete result"
            )

    def _record_failure(
        self,
        workspace_run_id: str,
        message: str,
        *,
        state: str = "failed",
    ) -> None:
        self._cancel_recovery_deadline()
        if self.budget is not None:
            self.recovery.account(workspace_run_id, None, self.budget.total_limit_tokens)
            self._save_recovery()
        if state == "cancelled" and self.recovery.stop_reason is None:
            self._stop_recovery("cancelled: The user stopped this workflow.")
        elif self.recovery.status == "running":
            self.recovery.status = "ready"
            self._save_recovery()
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
        self._capture_failure_context()

    def _prepare_dependencies(
        self,
        detection: ProjectDetection,
        cancel_event: threading.Event | None,
    ) -> DependencyBootstrapResult:
        """Prepare dependencies in the isolated copy or fail with the exact cause."""

        def output(stream: str, line: str) -> None:
            if line.strip():
                self.add_log(f"dependency {stream}: {line}")

        result = prepare_project_dependencies(
            detection,
            cancel_event=cancel_event,
            on_output=output,
        )
        with self.lock:
            self.dependency_bootstrap = result
        if result.status in {"prepared", "not_needed"}:
            self.add_log(result.message)
        else:
            self.add_log(result.message, "error")
            detail = result.message
            if result.stderr.strip() and result.stderr.strip() not in detail:
                detail = f"{detail} Details: {result.stderr.strip()[-1600:]}"
            raise RuntimeError(f"Dependency preparation blocked Verification: {detail}")
        return result

    def _verification_event(self, event: VerificationEvent) -> None:
        if event.text.strip():
            self.add_log(event.text, "error" if event.stream == "stderr" else "info")

    def decide_all(self, decision: str, *, relative_path: str | None = None) -> None:
        if self.review is None:
            raise RuntimeError("Review is not ready.")
        if decision not in {"accept", "revert"}:
            raise ValueError("decision must be accept or revert")
        report = self.review
        if relative_path is not None and relative_path not in {item.relative_path for item in report.files}:
            raise ValueError("file does not belong to this review")
        for item in tuple(report.files):
            if item.decision != "pending" or relative_path is not None and item.relative_path != relative_path:
                continue
            report = (
                self.review_store.accept(report.review_id, item.relative_path)
                if decision == "accept"
                else self.review_store.revert(report.review_id, item.relative_path)
            )
        if report.pending_count == 0 and report.accepted_count:
            checkpoint_accepted_changes(
                report.project_root,
                (
                    item.relative_path
                    for item in report.files
                    if item.decision == "accepted"
                ),
            )
        self.review = report
        if decision == "revert" and self.detection is not None:
            # A file decision changes the verified tree. Never export using
            # the passing evidence from the earlier, different file set.
            self.verification = None
            self.export = None
            verification = VerificationRuntime().run(
                detection=self.detection,
                evidence_root=self.verification_store.evidence_root,
                on_event=self._verification_event,
            )
            if verification.finalize_allowed:
                verification = finalize_verification(verification)
            self.verification = verification
            self.verification_store.save(verification)
            if verification.finalize_allowed:
                self._resolve_failure_memory_after_verification(verification)
            if self.active_task_id and self.run:
                runs = self.store.list_task_runs(self.active_task_id)
                if runs:
                    self._write_run_manifest(runs[0].run_id, codex_run_id=self.run.run_id,
                                             verification_id=verification.verification_id,
                                             review_id=report.review_id)
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="review" if report.pending_count else "accepted" if report.accepted_count else "reverted")
        self.message = "تصمیم روی تغییرات ثبت شد."

    def _release_gate(self) -> dict[str, Any]:
        """Return the evidence-backed conditions for creating a project ZIP."""

        blockers: list[str] = []
        review_blocker: str | None = None
        no_change_attested = self._run_has_attested_no_change()
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
            review_blocker = (
                f"{self.review.pending_count} changed file(s) still need a review decision."
            )
            blockers.append(review_blocker)
        elif self.review.status != "complete":
            blockers.append("Review has not completed.")
        elif self.detection is not None:
            try:
                review_drift = review_snapshot_drift(
                    self.detection.descriptor.root,
                    self.review.files,
                )
                blockers.extend(review_drift)
                delta = inspect_project_delta(
                    self.detection.descriptor.root,
                    self._baseline_snapshot_path(),
                )
                if delta.deleted_files:
                    blockers.append(
                        "The project has deleted file(s); restore them before creating a ZIP."
                    )
                elif not delta.changed_members:
                    blockers.append(
                        "No changed project files are available for a delta ZIP."
                    )
                else:
                    validate_changed_html_links(
                        self.detection.descriptor.root,
                        delta.changed_members,
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                blockers.append(str(exc))

        export_is_valid = bool(self.export and self.export.verified)
        if export_is_valid and self.export is not None:
            saved_manifest = self._load_release_manifest(self.export.manifest_path)
            if saved_manifest is not None and saved_manifest.get("schema_version") == 3:
                try:
                    validate_export_artifacts(
                        self.export.archive_path,
                        self.export.manifest_path,
                        self.export.checksum_path,
                        expected_sha256=self.export.sha256,
                        expected_file_count=self.export.file_count,
                        expected_changed_files=self.export.changed_files,
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    export_is_valid = False
                    blockers.append(f"The saved project ZIP is no longer valid: {exc}")
        hard_blockers = [item for item in blockers if item != review_blocker]
        if export_is_valid and not blockers:
            status = "exported"
        elif (
            no_change_attested
            and self.verification is not None
            and self.verification.finalize_allowed
            and self.review is not None
            and self.review.status == "complete"
            and not self.review.pending_count
            and blockers == ["No changed project files are available for a delta ZIP."]
        ):
            # A PASS-attested writer may discover that the requested state is
            # already present.  Verification remains authoritative, but a
            # no-op result is not a failed run and must be explained as such.
            status = "verified_no_change"
        elif review_blocker is not None and not hard_blockers:
            status = "awaiting_review"
        elif blockers:
            status = "blocked"
        else:
            status = "ready_for_export"
        return {
            "status": status,
            "ready": not blockers,
            "blockers": blockers,
            "exported": export_is_valid,
        }

    def _run_has_attested_no_change(self) -> bool:
        """Return whether every implementation writer reported a verified no-op."""

        if self.run is None or self.run.status != "completed" or self.graph is None:
            return False
        writer_ids = {
            node.node_id
            for node in self.graph.nodes
            if node.agent_role in {"frontend", "backend", "coordinator", "release"}
        }
        if not writer_ids:
            return False
        # Persisted/fixture run objects from older clients may only expose the
        # terminal status.  Treat those as not attested rather than crashing
        # release-gate rendering on a compatibility read.
        results = {
            item.node_id: item
            for item in getattr(self.run, "node_results", ())
            if getattr(item, "node_id", None)
        }
        for node_id in writer_ids:
            result = results.get(node_id)
            if (
                result is None
                or getattr(result, "status", None) != "completed"
                or getattr(result, "changed_files", ())
            ):
                return False
            normalized = (
                str(getattr(result, "summary", ""))
                .casefold()
                .replace("\u200c", " ")
                .replace("*", "")
            )
            if "empy_node_result: pass" not in normalized:
                return False
        return True

    def export_download_path(self) -> Path:
        """Return the current verified ZIP only when it is safe to download."""

        exported = self.export
        if exported is None or not exported.verified:
            raise RuntimeError("No verified project ZIP is ready for download.")
        workspace = self.workspace_root.resolve()
        archive = exported.archive_path.expanduser().resolve()
        try:
            archive.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeError("The verified ZIP is outside the Empy workspace.") from exc
        if archive.suffix.casefold() != ".zip" or not archive.is_file():
            raise RuntimeError("The verified project ZIP is no longer available.")
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != exported.sha256:
            raise RuntimeError("The verified project ZIP changed; export it again.")
        # Current exports carry a complete v3 integrity contract.  Validate
        # the ZIP and both sidecars on every download so a removed or edited
        # artifact cannot be served from a stale in-memory state.
        manifest = self._load_release_manifest(exported.manifest_path)
        if manifest is not None and manifest.get("schema_version") == 3:
            try:
                validate_export_artifacts(
                    archive,
                    exported.manifest_path,
                    exported.checksum_path,
                    expected_sha256=exported.sha256,
                    expected_file_count=exported.file_count,
                    expected_changed_files=exported.changed_files,
                    workspace_root=workspace,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RuntimeError(f"The verified project export is no longer valid: {exc}") from exc
        return archive

    def export_artifact_path(self, kind: str) -> Path:
        """Return a verified export sidecar without exposing arbitrary files."""

        if kind == "archive":
            return self.export_download_path()
        exported = self.export
        if exported is None or not exported.verified:
            raise RuntimeError("No verified project ZIP is ready for download.")
        if kind == "manifest":
            target = exported.manifest_path
        elif kind == "checksum":
            target = exported.checksum_path
        else:
            raise ValueError("unknown export artifact")
        workspace = self.workspace_root.resolve()
        target = target.expanduser().resolve()
        try:
            target.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeError("The export sidecar is outside the Empy workspace.") from exc
        if not target.is_file():
            raise RuntimeError("The export sidecar is no longer available; export again.")
        if kind == "checksum":
            expected = f"{exported.sha256}  {exported.archive_path.name}"
            if target.read_text(encoding="utf-8").strip() != expected:
                raise RuntimeError("The export checksum changed; export the project again.")
            manifest = self._load_release_manifest(exported.manifest_path)
            if manifest is not None and manifest.get("schema_version") == 3:
                try:
                    validate_export_artifacts(
                        exported.archive_path,
                        exported.manifest_path,
                        target,
                        expected_sha256=exported.sha256,
                        expected_file_count=exported.file_count,
                        expected_changed_files=exported.changed_files,
                        workspace_root=workspace,
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"The export checksum is no longer trusted: {exc}"
                    ) from exc
        if kind == "manifest":
            try:
                manifest = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("The export manifest is invalid; export the project again.") from exc
            if (
                not isinstance(manifest, dict)
                or manifest.get("archive_mode") != "delta"
                or tuple(manifest.get("changed_files", ())) != exported.changed_files
            ):
                raise RuntimeError("The export manifest does not match the verified ZIP.")
            if manifest.get("schema_version") == 3:
                try:
                    validate_export_artifacts(
                        exported.archive_path,
                        target,
                        exported.checksum_path,
                        expected_sha256=exported.sha256,
                        expected_file_count=exported.file_count,
                        expected_changed_files=exported.changed_files,
                        workspace_root=workspace,
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"The export manifest is no longer trusted: {exc}"
                    ) from exc
        return target

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
        exported = export_project_zip(
            self.detection.descriptor.root,
            target,
            baseline_snapshot=self._baseline_snapshot_path(),
            review_files=self.review.files,
        )
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
        self.message = "فایل ZIP فقط شامل فایل‌های تغییرکرده آماده شد."
        if self.active_task_id is not None:
            self.store.update_task(self.active_task_id, status="released")

    def new_ticket(self) -> None:
        if self.running:
            raise RuntimeError("Stop the active run before starting another ticket.")
        if self.active_project_id is None:
            raise RuntimeError("Choose a project first.")
        self.active_task_id = None
        self.task = self.plan = self.context = self.budget = self.graph = None
        self.run = self.verification = self.review = self.export = None
        self.benchmark = None
        self.continuation_context = self.failure_context = None
        self.error = None
        self.repair_attempts = 0
        self.recovery = RecoveryState(policy=self.recovery.policy)
        self.phase = "task"
        self.store.set_setting("active_task_id", None)
        self._save_recovery()
        self._refresh_failure_memory_view()

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
            self.dependency_bootstrap = None
            self.import_report = None
            self.runtime = None
            self.cancel_event = None
            self.phase = "project"
            self.message_level = "info"
            self.error = None
            self.continuation_context = None
            self.failure_context = None
            self.repair_attempts = 0
            self.message = ""
            self.logs.clear()
        self.store.set_setting("active_project_id", None)
        self.store.set_setting("active_task_id", None)
        self._refresh_failure_memory_view()

    def public(self) -> dict[str, Any]:
        self._refresh_failure_memory_view()
        with self.lock:
            inspection = self.driver.inspect(refresh=False)
            project = self._active_project()
            tasks = project["tasks"] if project else []
            task_request = self.recovery.original_request
            if self.active_task_id:
                try:
                    task_request = self.store.get_task(self.active_task_id).request_text
                except KeyError:
                    pass
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
                    "task_request": task_request,
                    "budget_preset": self.budget_preset,
                    "model_route": self.model_route.to_dict(),
                    "route_locked": self.running or self._starting_run or (self.recovery.started_at is not None and self.recovery.stop_reason is None),
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
                    "export": self._public_export(),
                    "dependency_bootstrap": self._public_dependency_bootstrap(),
                    "failure_context": self._localized_failure_context(),
                    "failure_memory": {
                        "open_count": self.failure_memory_open_count,
                        "matched_count": len(self.failure_memory_matches),
                        "blocked": self.failure_memory_blocked,
                        "block_reason": self.failure_memory_block_reason,
                        "hint": self.failure_memory_hint,
                        "records": [
                            record.compact_summary()
                            for record in self.failure_memory_matches[:8]
                        ],
                    },
                    "recovery": self.recovery.to_dict(),
                    "import_report": self.import_report,
                    "release_gate": self._release_gate(),
                    "engine": {
                        "provider": inspection.display_name,
                        "availability": inspection.availability,
                        "ready": not self.route_settings_error and inspection.availability == "available" and inspection.authenticated,
                        "version": inspection.version,
                        "message": self.route_settings_error or inspection.message,
                        "remediation": inspection.remediation,
                    },
                }
            ))

    def _public_export(self) -> dict[str, Any] | None:
        if self.export is None:
            return None
        value = cast(dict[str, Any], self.export.to_dict())
        value.update(
            {
                "archive_name": self.export.archive_path.name,
                "manifest_name": self.export.manifest_path.name,
                "checksum_name": self.export.checksum_path.name,
                "manifest_available": self.export.manifest_path.is_file(),
                "checksum_available": self.export.checksum_path.is_file(),
            }
        )
        return value

    def _public_dependency_bootstrap(self) -> dict[str, Any] | None:
        result = self.dependency_bootstrap
        if result is None:
            return None
        value = result.to_dict()
        value["root"] = self._workspace_reference(result.root)
        value["command"] = [
            Path(part).name if index == 0 else part
            for index, part in enumerate(result.command)
        ]
        value["stdout"] = _safe_verification_detail(
            result.stdout,
            (
                self.detection.descriptor.root
                if self.detection is not None
                else self.workspace_root,
                self.workspace_root,
            ),
        ) if result.stdout.strip() else ""
        value["stderr"] = _safe_verification_detail(
            result.stderr,
            (
                self.detection.descriptor.root
                if self.detection is not None
                else self.workspace_root,
                self.workspace_root,
            ),
        ) if result.stderr.strip() else ""
        return value

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

        run_error = (
            self.run.error_message.casefold()
            if self.run is not None and self.run.error_message
            else ""
        )
        token_budget_run_failure = (
            self.run is not None
            and self.run.status != "completed"
            and (
                self.run.error_code == "budget_exceeded"
                or "fresh-token limit" in run_error
                or "token budget" in run_error
                or "token guard" in run_error
                or "سقف مصرف" in (self.run.error_message or "")
            )
        )
        if token_budget_run_failure:
            repair_available = self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running"
            if self.language == "en":
                return {
                    "kind": "token_budget",
                    "title": "This step used too many tokens",
                    "summary": "Empy stopped the step before a complete result was produced; no ZIP is ready.",
                    "steps": [
                        "Choose Automatically repair and rerun; Empy will retry the same change with a compact context.",
                        "If the compact retry also reaches the limit, split the ticket into two smaller requests instead of repeating it.",
                    ],
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "token_budget",
                "title": "مصرف توکن این مرحله بیش از حد شد",
                "summary": "Empy مرحله را قبل از تولید نتیجهٔ کامل متوقف کرد؛ ZIP هنوز آماده نیست.",
                "steps": [
                    "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ همان تغییر با context کوچک‌تر اجرا می‌شود.",
                    "اگر اجرای کوچک‌تر هم به سقف رسید، تیکت را به دو درخواست کوچک‌تر تقسیم کنید؛ اجرای تکراری انجام نمی‌شود.",
                ],
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }

        run_error_text = (
            self.run.error_message
            if self.run is not None and self.run.error_message
            else self.error or ""
        )
        run_failure_kind = _failure_kind(run_error_text)
        if self.run is not None and self.run.status != "completed":
            # Prefer the specific worker evidence recovered by the failure
            # context over the graph's generic objective_not_met message.
            refreshed_context = self._failure_context_from_state()
            contextual_failures = (refreshed_context or {}).get("failures", [])
            contextual_kind = next(
                (
                    str(item.get("kind", ""))
                    for item in contextual_failures
                    if str(item.get("kind", ""))
                    in {
                        "ownership_mismatch",
                        "no_writable_files",
                        "token_budget",
                        "dirty_worktree",
                        "no_change",
                    }
                ),
                "",
            )
            if contextual_kind:
                run_failure_kind = contextual_kind
        if run_failure_kind == "ownership_mismatch":
            repair_available = (
                self.repair_attempts < self.recovery.policy.max_attempts
                and self.recovery.status != "running"
            )
            if self.language == "en":
                return {
                    "kind": "ownership_mismatch",
                    "title": "The selected file target does not match this project",
                    "summary": (
                        "Empy found the requested work, but the Agent was assigned a file outside the project's real layout. "
                        "No unapproved file was changed."
                    ),
                    "steps": [
                        (
                            "Choose Automatically repair and rerun. Empy will refresh the project map and assign the real target."
                            if repair_available
                            else "Choose Continue and fix ticket after selecting the real project target."
                        ),
                    ],
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "ownership_mismatch",
                "title": "هدف فایل با ساختار واقعی پروژه یکی نیست",
                "summary": (
                    "Empy کار درخواستی را پیدا کرد، اما Agent به فایلی خارج از ساختار واقعی پروژه وصل شده بود؛ "
                    "هیچ فایل تأییدنشده‌ای تغییر نکرده است."
                ),
                "steps": [
                    (
                        "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy فهرست پروژه را تازه می‌کند و فایل واقعی را انتخاب می‌کند."
                        if repair_available
                        else "پس از انتخاب هدف واقعی پروژه، روی «ادامه و اصلاح تیکت» بزنید."
                    ),
                ],
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }
        if run_failure_kind == "no_change":
            repair_available = (
                self.repair_attempts < self.recovery.policy.max_attempts
                and self.recovery.status != "running"
            )
            if self.language == "en":
                return {
                    "kind": "no_change",
                    "title": "The Agent made no change without a verifiable PASS",
                    "summary": (
                        "The Agent produced no project change and did not provide the "
                        "required PASS attestation, so Empy stopped before Verification."
                    ),
                    "steps": [
                        (
                            "Choose Automatically repair and rerun. Empy will verify "
                            "whether the requested state already exists or make the "
                            "bounded change."
                            if repair_available
                            else "Choose Continue and fix ticket to retry the bounded work."
                        ),
                    ],
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "no_change",
                "title": "Agent بدون تأیید PASS تغییری ایجاد نکرد",
                "summary": (
                    "Agent هیچ فایل پروژه را تغییر نداد و تأیید صریح PASS ارائه نکرد؛ "
                    "Empy پیش از Verification متوقف شد."
                ),
                "steps": [
                    (
                        "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy بررسی می‌کند "
                        "وضعیت درخواستی از قبل وجود دارد یا تغییر محدود لازم است."
                        if repair_available
                        else "برای تلاش دوباره روی «ادامه و اصلاح تیکت» بزنید."
                    ),
                ],
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }
        if run_failure_kind == "dirty_worktree":
            repair_available = self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running"
            if self.language == "en":
                return {
                    "kind": "dirty_worktree",
                    "title": "The previous attempt needs a safe retry",
                    "summary": (
                        "The Agent stopped before the next step because the isolated copy still has changes from the previous attempt. "
                        "Your original project is unchanged."
                    ),
                    "steps": (
                        [
                            "Choose Safely reset and continue. Empy preserves the previous attempt, resets only the isolated copy, and retries the ticket.",
                        ]
                        if repair_available
                        else [
                            "Choose Continue and fix ticket to retry from the preserved isolated baseline.",
                        ]
                    ),
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "dirty_worktree",
                "title": "تلاش قبلی نیاز به ادامهٔ امن دارد",
                "summary": (
                    "Agent قبل از مرحلهٔ بعد متوقف شد چون کپی ایزوله تغییرات تلاش قبلی را دارد. "
                    "فایل اصلی پروژهٔ شما تغییر نکرده است."
                ),
                "steps": (
                    [
                        "روی «پاک‌سازی امن و ادامه» بزنید؛ Empy تلاش قبلی را حفظ می‌کند، فقط کپی ایزوله را پاک‌سازی می‌کند و تیکت را دوباره ادامه می‌دهد.",
                    ]
                    if repair_available
                    else [
                        "روی «ادامه و اصلاح تیکت» بزنید تا از مبنای ایزولهٔ حفظ‌شده دوباره ادامه داده شود.",
                    ]
                ),
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }

        contract_mismatch = next(
            (
                item
                for item in failures
                if str(item.get("kind", "")) == "verification_contract_mismatch"
            ),
            None,
        )
        if contract_mismatch is not None:
            finding = str(
                contract_mismatch.get("user_finding")
                or _plain_failure_finding(
                    "verification_contract_mismatch",
                    str(contract_mismatch.get("detail", "")),
                    language=self.language,
                )
            )
            repair_available = self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running"
            if self.language == "en":
                return {
                    "kind": "verification_contract_mismatch",
                    "title": "The home page was not delivered",
                    "summary": finding,
                    "steps": (
                        [
                            "Choose Automatically repair and rerun. Empy will update only the isolated copy.",
                            "Empy will run the same Verification again; the ZIP stays blocked until it really passes.",
                        ]
                        if repair_available
                        else [
                            "Automatic repair has already been tried once. Review the project decision and run the exact corrective ticket again.",
                        ]
                    ),
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "verification_contract_mismatch",
                "title": "صفحهٔ اول ساخته نشد",
                "summary": finding,
                "steps": (
                    [
                        "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy فقط کپی ایزوله را تغییر می‌دهد.",
                        "Empy همان Verification را دوباره اجرا می‌کند؛ ZIP تا موفقیت واقعی ساخته نمی‌شود.",
                    ]
                    if repair_available
                    else [
                        "اصلاح خودکار یک‌بار انجام شده است؛ برای تصمیم بعدی، تیکت اصلاحی دقیق را دوباره اجرا کنید.",
                    ]
                ),
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }

        verification_failed = self.verification is not None and (
            self.verification.status != "pass"
            or not self.verification.finalize_allowed
            or self.verification.finalized_at is None
        )
        if verification_failed:
            repair_available = self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running"
            if self.language == "en":
                return {
                    "kind": "verification_failed",
                    "title": "A project check did not pass",
                    "summary": (
                        "Empy found a problem in the project checks, so it has blocked the ZIP."
                    ),
                    "steps": [
                        "Choose Automatically repair and rerun; Empy will use the confirmed finding in the isolated copy.",
                        "The ZIP will unlock only after the same Verification really passes.",
                    ],
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "verification_failed",
                "title": "یک بررسی پروژه موفق نشد",
                "summary": "Empy در بررسی پروژه مشکل پیدا کرد؛ برای جلوگیری از ZIP ناقص، خروجی مسدود شد.",
                "steps": [
                    "روی «اصلاح خودکار و اجرای دوباره» بزنید؛ Empy از همین یافته برای اصلاح کپی ایزوله استفاده می‌کند.",
                    "ZIP فقط بعد از موفقیت واقعی همان Verification فعال می‌شود.",
                ],
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
            }

        if self.run is not None and self.run.status != "completed":
            repair_available = self.repair_attempts < self.recovery.policy.max_attempts and self.recovery.status != "running"
            if self.language == "en":
                return {
                    "kind": "run_failed",
                    "title": "The Agent run did not finish",
                    "summary": "The result is not safe to deliver because the Agent run did not complete.",
                    "steps": [
                        (
                            "Choose Automatically repair and rerun to retry the work in the isolated copy."
                            if repair_available
                            else "Choose Continue and fix ticket to retry the work in the isolated copy."
                        ),
                        "Review the result and Verification before creating a ZIP.",
                    ],
                    "action": "auto-repair" if repair_available else "resume-ticket",
                    "repair_available": repair_available,
                }
            return {
                "kind": "run_failed",
                "title": "اجرای Agentها کامل نشد",
                "summary": "چون اجرای Agentها کامل نشده است، نتیجه برای تحویل امن نیست.",
                "steps": [
                    (
                        "برای اصلاح خودکار و اجرای دوباره روی «اصلاح خودکار و اجرای دوباره» بزنید."
                        if repair_available
                        else "برای تلاش دوباره روی «ادامه و اصلاح تیکت» بزنید."
                    ),
                    "قبل از ساخت ZIP، نتیجه و Verification را مرور کنید.",
                ],
                "action": "auto-repair" if repair_available else "resume-ticket",
                "repair_available": repair_available,
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
        verification_failures: list[dict[str, Any]] = []
        verification_roots = (
            self.detection.descriptor.root if self.detection is not None else self.workspace_root,
            self.workspace_root,
        )
        for item in verification_results:
            if item.status != "fail":
                continue
            detail = _safe_verification_detail(
                item.stderr or item.stdout,
                verification_roots,
            )
            detail, inferred_kind = _add_entrypoint_hint(detail, self.detection)
            kind = inferred_kind or _failure_kind(detail)
            verification_failures.append(
                {
                    "check_id": item.check.check_id,
                    "label": item.check.label,
                    "category": item.check.category,
                    "returncode": item.returncode,
                    "detail": detail,
                    "kind": kind,
                    "user_finding": _plain_failure_finding(
                        kind,
                        detail,
                        language=self.language,
                    ),
                }
            )
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
            "model_route": self.store.get_setting(f"run-route.v1.{self.run.run_id}"),
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
            "budget_accounting": self.run.budget_accounting.to_dict() if self.run.budget_accounting else None,
            "context_manifest": self.run.context_manifest.to_dict() if self.run.context_manifest else None,
            "task_ledger": self.run.task_ledger.to_dict() if self.run.task_ledger else None,
            "route_report": self.run.route_report.to_dict() if self.run.route_report else None,
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
                "archive_mode": self.export.archive_mode if self.export is not None else None,
                "changed_files": list(self.export.changed_files) if self.export is not None else [],
                "deleted_files": list(self.export.deleted_files) if self.export is not None else [],
                "extraction_root": self.export.extraction_root if self.export is not None else None,
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

    def _send_download(self, target: Path, content_type: str = "application/zip") -> None:
        filename = target.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        ascii_filename = filename.encode("ascii", "ignore").decode("ascii") or "download"
        encoded_filename = quote(filename, safe="")
        size = target.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
        )
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with target.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)

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
        if parsed.path == "/api/export/download":
            try:
                archive = self.app.state.export_download_path()
            except (OSError, RuntimeError, ValueError) as exc:
                message = safe_user_error(exc, language=self.app.state.language)
                self._send_json({"error": message}, 409)
                return
            self._send_download(archive)
            return
        if parsed.path in {"/api/export/manifest", "/api/export/checksum"}:
            kind = "manifest" if parsed.path.endswith("manifest") else "checksum"
            try:
                target = self.app.state.export_artifact_path(kind)
            except (OSError, RuntimeError, ValueError) as exc:
                message = safe_user_error(exc, language=self.app.state.language)
                self._send_json({"error": message}, 409)
                return
            content_type = (
                "application/json; charset=utf-8"
                if kind == "manifest"
                else "text/plain; charset=utf-8"
            )
            self._send_download(target, content_type)
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
        elif path == "/api/task/new":
            state.new_ticket()
        elif path == "/api/plan":
            state.create_plan(str(body.get("tasks", "")), body.get("task_id"), budget_preset=body.get("budget_preset"))
        elif path == "/api/benchmark":
            state.run_benchmark()
        elif path == "/api/run":
            state.start_run()
        elif path == "/api/cancel":
            state.cancel_run()
        elif path == "/api/resume-ticket":
            state.resume_ticket()
        elif path == "/api/auto-repair":
            state.auto_repair()
        elif path == "/api/recovery-policy":
            state.set_recovery_policy(body)
        elif path == "/api/decision":
            state.decide_all(str(body.get("decision", "")), relative_path=body.get("relative_path"))
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
        elif path == "/api/model-route":
            state.set_model_route(body)
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
    restore_session: bool = True,
) -> AppServer:
    state = GuidedState(Path(workspace), restore_session=restore_session)
    return AppServer(("127.0.0.1", port), state, token or secrets.token_urlsafe(24))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Empy Studio bilingual guided desktop UI")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=None)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--start-page", action="store_true", help="Open the project screen without restoring the last ticket")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Start a new empty workspace for this session",
    )
    args = parser.parse_args(argv)
    workspace = (
        clean_workspace_root()
        if args.clean
        else args.workspace or default_workspace_root()
    )
    server = create_server(workspace=workspace, token=args.token, port=args.port, restore_session=not args.start_page)
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
