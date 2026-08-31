from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Final, Literal, cast

from empy_studio.core import (
    DriverCapabilities,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverInspection,
    DriverStatus,
)
from empy_studio.token_usage import TokenUsage

from ..codex_preflight import (
    CodexHostDiagnostic,
    detect_codex_host_diagnostic,
    diagnose_codex_os_error,
)
from .base import BaseDriver

CodexAvailability = Literal[
    "available",
    "missing",
    "unauthenticated",
    "unavailable",
]
CodexSandboxMode = Literal[
    "read-only",
    "workspace-write",
    "danger-full-access",
]
CodexNodeStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "unavailable",
    "skipped",
]
CodexErrorCode = Literal[
    "installation_missing",
    "authentication_required",
    "permission_denied",
    "rate_limited",
    "network_error",
    "sandbox_error",
    "invalid_output",
    "process_failed",
    "launch_failed",
    "timeout",
    "cancelled",
    "dirty_worktree",
    "scope_violation",
    "budget_exceeded",
    "objective_not_met",
]
CodexEventLevel = Literal["info", "warning", "error"]

DEFAULT_PREFLIGHT_TIMEOUT: Final[float] = 8.0
DEFAULT_CANCEL_GRACE_SECONDS: Final[float] = 2.0
MAX_PREFLIGHT_OUTPUT_CHARS: Final[int] = 16_384


@dataclass(frozen=True)
class CodexInstallation:
    availability: CodexAvailability
    executable: str | None
    version: str | None
    authenticated: bool
    message: str
    remediation: str | None = None
    error_code: CodexErrorCode | None = None

    @property
    def ready(self) -> bool:
        return self.availability == "available"

    def validate(self) -> None:
        if self.availability == "available":
            if self.executable is None or self.version is None:
                raise ValueError("available Codex installation requires executable and version")
            if not self.authenticated:
                raise ValueError("available Codex installation must be authenticated")
        if not self.message.strip():
            raise ValueError("Codex installation message cannot be empty")

    @property
    def terminal_error_code(self) -> CodexErrorCode:
        if self.error_code is not None:
            return self.error_code
        if self.availability == "missing":
            return "installation_missing"
        if self.availability == "unauthenticated":
            return "authentication_required"
        return "launch_failed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CodexProgressEvent:
    timestamp: str
    level: CodexEventLevel
    event_type: str
    message: str
    node_id: str | None = None
    raw: dict[str, object] | None = None

    def validate(self) -> None:
        if not self.timestamp or not self.event_type or not self.message.strip():
            raise ValueError("Codex progress event fields cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CodexNodeExecution:
    node_id: str
    task_id: str
    status: CodexNodeStatus
    started_at: str
    finished_at: str
    return_code: int | None
    thread_id: str | None
    summary: str
    changed_files: tuple[str, ...]
    event_count: int
    events_path: str
    stderr_path: str
    final_message_path: str
    command_path: str
    error_code: CodexErrorCode | None = None
    error_message: str | None = None
    usage: TokenUsage | None = None

    def validate(self) -> None:
        if not self.node_id or not self.task_id:
            raise ValueError("Codex node execution identity cannot be empty")
        if self.status not in {
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "timed_out",
            "unavailable",
            "skipped",
        }:
            raise ValueError(f"unsupported Codex node status: {self.status}")
        if not self.summary.strip():
            raise ValueError("Codex node execution summary cannot be empty")
        if self.status == "completed" and self.return_code != 0:
            raise ValueError("completed Codex node execution requires return code 0")
        if (
            self.status in {"failed", "cancelled", "timed_out", "unavailable"}
            and (self.error_code is None or not self.error_message)
        ):
            raise ValueError(
                "failed Codex node execution requires mapped error details"
            )

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["usage"] = self.usage.to_dict() if self.usage is not None else None
        return value


class CodexDriverError(RuntimeError):
    def __init__(self, code: CodexErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessFactory = Callable[..., subprocess.Popen[str]]
ProgressCallback = Callable[[CodexProgressEvent], None]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


class CodexDriver(BaseDriver):
    """Production Codex CLI driver with bounded execution and live evidence."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        artifact_root: str | Path | None = None,
        enabled: bool = True,
        fallback_executables: Sequence[str | Path] | None = None,
        sandbox_mode: CodexSandboxMode | None = None,
        command_runner: CommandRunner | None = None,
        process_factory: ProcessFactory | None = None,
        monotonic: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
    ) -> None:
        self.requested_executable = executable
        self.enabled = enabled
        self.sandbox_mode = sandbox_mode
        default_fallbacks: tuple[str | Path, ...] = (
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
            Path.home() / ".npm-global" / "bin" / "codex",
            Path.home() / ".local" / "bin" / "codex",
        )
        self.fallback_executables = tuple(
            Path(item).expanduser()
            for item in (
                default_fallbacks
                if fallback_executables is None
                else fallback_executables
            )
        )
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve()
            if artifact_root is not None
            else Path.home() / ".empy-studio" / "codex-runs"
        )
        self.command_runner = (
            command_runner
            if command_runner is not None
            else cast(CommandRunner, subprocess.run)
        )
        self.process_factory = (
            process_factory
            if process_factory is not None
            else cast(ProcessFactory, subprocess.Popen)
        )
        self.monotonic = monotonic
        self.sleep = sleep
        self._status: DriverStatus = "unavailable"
        self._process_lock = threading.Lock()
        self._active_processes: dict[int, subprocess.Popen[str]] = {}
        self._cancel_requested = threading.Event()
        self._installation: CodexInstallation | None = None

    @property
    def provider_id(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "Codex"

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            planning=False,
            code_editing=True,
            verification=True,
            streaming=True,
            cancellation=True,
        )

    @property
    def supports_parallel_nodes(self) -> bool:
        """Codex processes can run concurrently when file ownership is disjoint."""
        return True

    def status(self) -> DriverStatus:
        return self._status

    def begin_run(self) -> None:
        """Clear cancellation left by a previous, already-terminal run."""
        self._cancel_requested.clear()

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        if not self.enabled:
            inspection = DriverInspection(
                provider_id=self.provider_id,
                display_name=self.display_name,
                availability="disabled",
                implemented=True,
                enabled=False,
                executable=self.requested_executable,
                version=None,
                authenticated=False,
                message="Codex is disabled in Empy Studio settings.",
                remediation="Enable Codex in Settings before running a graph.",
            )
            inspection.validate()
            return inspection
        installation = self.inspect_installation(refresh=refresh)
        inspection = DriverInspection(
            provider_id=self.provider_id,
            display_name=self.display_name,
            availability=installation.availability,
            implemented=True,
            enabled=True,
            executable=installation.executable,
            version=installation.version,
            authenticated=installation.authenticated,
            message=installation.message,
            remediation=installation.remediation,
        )
        inspection.validate()
        return inspection

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        if not self.enabled:
            installation = CodexInstallation(
                availability="unavailable",
                executable=self.requested_executable,
                version=None,
                authenticated=False,
                message="Codex is disabled in Empy Studio settings.",
                remediation="Enable Codex in Settings before running a graph.",
            )
            installation.validate()
            self._installation = installation
            self._status = "unavailable"
            return installation
        if self._installation is not None and not refresh:
            return self._installation

        executables = self._candidate_executables()
        if not executables:
            installation = CodexInstallation(
                availability="missing",
                executable=None,
                version=None,
                authenticated=False,
                message="Codex CLI was not found on this system.",
                remediation="Install Codex CLI, then reopen Empy Studio.",
            )
            installation.validate()
            self._installation = installation
            self._status = "unavailable"
            return installation

        last_installation: CodexInstallation | None = None
        last_error: OSError | subprocess.TimeoutExpired | None = None
        for executable in executables:
            try:
                installation = self._inspect_candidate(executable)
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                continue
            last_installation = installation
            if installation.ready:
                self._installation = installation
                self._status = "available"
                return installation

        if last_installation is not None:
            self._installation = last_installation
            self._status = "unavailable"
            return last_installation

        error = last_error or OSError("Codex preflight failed")
        diagnostic = (
            diagnose_codex_os_error(error)
            if isinstance(error, OSError)
            else CodexHostDiagnostic(
                code="sandbox",
                message="Codex preflight timed out in this environment.",
                remediation="Check the host permissions and refresh the environment.",
            )
        )
        installation = CodexInstallation(
            availability="unavailable",
            executable=None,
            version=None,
            authenticated=False,
            message=diagnostic.message,
            remediation=diagnostic.remediation,
            error_code="sandbox_error",
        )
        installation.validate()
        self._installation = installation
        self._status = "unavailable"
        return installation

    def _inspect_candidate(self, executable: str) -> CodexInstallation:
        host_diagnostic: CodexHostDiagnostic | None = None
        version_result = self._run_preflight([executable, "--version"])
        version_stdout = self._bounded_output(version_result.stdout)
        version_stderr = self._bounded_output(version_result.stderr)
        version = (version_stdout or version_stderr).strip()
        host_diagnostic = detect_codex_host_diagnostic(version_stdout, version_stderr)
        if version_result.returncode != 0 or not version:
            return self._unavailable_installation(
                executable,
                version=version or None,
                message=(
                    host_diagnostic.message
                    if host_diagnostic is not None
                    else "Codex CLI is installed but its version check failed."
                ),
                remediation=(
                    host_diagnostic.remediation
                    if host_diagnostic is not None
                    else "Reinstall or update Codex CLI."
                ),
                error_code="sandbox_error" if host_diagnostic is not None else None,
            )

        exec_result = self._run_preflight([executable, "exec", "--help"])
        exec_stdout = self._bounded_output(exec_result.stdout)
        exec_stderr = self._bounded_output(exec_result.stderr)
        host_diagnostic = host_diagnostic or detect_codex_host_diagnostic(
            exec_stdout,
            exec_stderr,
        )
        if exec_result.returncode != 0:
            return self._unavailable_installation(
                executable,
                version=version,
                message=(
                    host_diagnostic.message
                    if host_diagnostic is not None
                    else "This Codex CLI installation does not provide non-interactive execution."
                ),
                remediation=(
                    host_diagnostic.remediation
                    if host_diagnostic is not None
                    else "Update Codex CLI to a version that supports `codex exec`."
                ),
                error_code="sandbox_error" if host_diagnostic is not None else None,
            )

        auth_result = self._run_preflight([executable, "login", "status"])
        auth_stdout = self._bounded_output(auth_result.stdout)
        auth_stderr = self._bounded_output(auth_result.stderr)
        host_diagnostic = host_diagnostic or detect_codex_host_diagnostic(
            auth_stdout,
            auth_stderr,
        )
        if auth_result.returncode != 0:
            return self._unavailable_installation(
                executable,
                version=version,
                message="Codex CLI is installed but is not signed in.",
                remediation="Run `codex login` once, then retry from Empy Studio.",
                availability="unauthenticated",
            )
        if host_diagnostic is not None:
            return self._unavailable_installation(
                executable,
                version=version,
                authenticated=True,
                message=host_diagnostic.message,
                remediation=host_diagnostic.remediation,
                error_code="sandbox_error",
            )
        return CodexInstallation(
            availability="available",
            executable=executable,
            version=version,
            authenticated=True,
            message="Codex CLI is installed, authenticated, and ready.",
        )

    def _run_preflight(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.command_runner(
            command,
            text=True,
            capture_output=True,
            timeout=DEFAULT_PREFLIGHT_TIMEOUT,
            check=False,
            env=self._runtime_environment(command[0] if command else None),
        )

    def _runtime_environment(
        self,
        executable: str | Path | None = None,
    ) -> dict[str, str]:
        """Build a usable child environment for GUI-launched CLI shims.

        Finder-launched macOS applications do not inherit the shell's PATH. A
        Codex executable installed through npm is commonly a small script with
        ``#!/usr/bin/env node``; finding the script is therefore not enough.
        Put the executable's directory and the common Node installation
        directories ahead of the inherited PATH for both preflight and real
        runs. The same rule is harmless on other platforms and keeps the
        provider process contract identical in the desktop and terminal apps.
        """
        environment = os.environ.copy()
        environment.setdefault("NO_COLOR", "1")

        additions: list[str] = []

        def add_directory(value: str | Path | None) -> None:
            if value is None:
                return
            candidate = Path(value).expanduser()
            try:
                if candidate.is_dir():
                    normalized = str(candidate)
                    if normalized not in additions:
                        additions.append(normalized)
            except OSError:
                return

        if executable:
            executable_path = Path(executable).expanduser()
            if executable_path.is_absolute():
                add_directory(executable_path.parent)

        home: Path | None
        try:
            home = Path.home()
        except OSError:
            home = None

        common_directories: tuple[str | Path, ...] = (
            "/opt/homebrew/bin",
            "/opt/homebrew/opt/node/bin",
            "/usr/local/bin",
            "/usr/local/opt/node/bin",
            "/usr/bin",
            "/bin",
        )
        for directory in common_directories:
            add_directory(directory)
        if home is not None:
            for directory in (
                home / ".local" / "bin",
                home / ".npm-global" / "bin",
                home / ".volta" / "bin",
                home / ".asdf" / "shims",
            ):
                add_directory(directory)
        for environment_name in (
            "NVM_SYMLINK",
            "NVM_HOME",
            "ProgramFiles",
            "ProgramFiles(x86)",
            "LOCALAPPDATA",
            "APPDATA",
        ):
            value = environment.get(environment_name)
            if value:
                add_directory(value)
                add_directory(Path(value) / "nodejs")
                add_directory(Path(value) / "Programs" / "nodejs")
                add_directory(Path(value) / "npm")

        inherited = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
        for item in inherited:
            if item not in additions:
                additions.append(item)
        environment["PATH"] = os.pathsep.join(additions)
        return environment

    @staticmethod
    def _bounded_output(value: str | None) -> str:
        if not value:
            return ""
        if len(value) <= MAX_PREFLIGHT_OUTPUT_CHARS:
            return value
        return value[:MAX_PREFLIGHT_OUTPUT_CHARS] + "…"

    @staticmethod
    def _unavailable_installation(
        executable: str,
        *,
        version: str | None,
        message: str,
        remediation: str,
        authenticated: bool = False,
        availability: CodexAvailability = "unavailable",
        error_code: CodexErrorCode | None = None,
    ) -> CodexInstallation:
        installation = CodexInstallation(
            availability=availability,
            executable=executable,
            version=version,
            authenticated=authenticated,
            message=message,
            remediation=remediation,
            error_code=error_code,
        )
        installation.validate()
        return installation

    def execute(self, request: DriverExecutionRequest) -> DriverExecutionResult:
        artifact_dir = self.artifact_root / request.task_id.replace(":", "-")
        node = self.execute_streaming(
            request,
            node_id=request.task_id,
            artifact_dir=artifact_dir,
        )
        result = DriverExecutionResult(
            status=self._driver_status_for_node(node.status),
            return_code=node.return_code,
            summary=node.summary,
            changed_files=node.changed_files,
        )
        result.validate()
        return result

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress: ProgressCallback | None = None,
    ) -> CodexNodeExecution:
        request.validate()
        installation = self.inspect_installation()
        if not installation.ready or installation.executable is None:
            message = installation.message
            if installation.remediation:
                message = f"{message} {installation.remediation}"
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=Path(artifact_dir),
                status="unavailable",
                started_at=self._utc_now(),
                return_code=None,
                summary="Codex execution could not start.",
                error_code=installation.terminal_error_code,
                error_message=message,
            )

        run_dir = Path(artifact_dir).expanduser().resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.jsonl"
        stderr_path = run_dir / "stderr.log"
        final_message_path = run_dir / "final-message.md"
        command_path = run_dir / "command.json"
        command = self.build_command(
            request,
            executable=installation.executable,
            final_message_path=final_message_path,
        )
        command_path.write_text(
            json.dumps(
                {"argv": command, "cwd": str(request.project.root)},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        started_at = self._utc_now()
        self._status = "running"
        self._emit(
            on_progress,
            level="info",
            event_type="run.started",
            message=f"Starting Codex for {node_id}",
            node_id=node_id,
        )

        process_environment = self._runtime_environment(command[0])

        if self._cancel_requested.is_set():
            self._status = "cancelled"
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="cancelled",
                started_at=started_at,
                return_code=None,
                summary="Codex execution was cancelled before the process started.",
                error_code="cancelled",
                error_message="The user cancelled this Codex run.",
            )

        try:
            process = self.process_factory(
                command,
                cwd=request.project.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=process_environment,
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            self._status = "failed"
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="failed",
                started_at=started_at,
                return_code=None,
                summary="Codex process could not be launched.",
                error_code="launch_failed",
                error_message=str(exc),
            )

        process_key = id(process)
        with self._process_lock:
            self._active_processes[process_key] = process

        events: list[dict[str, object]] = []
        stderr_lines: list[str] = []
        thread_id: str | None = None
        parse_error: str | None = None
        budget_exceeded = threading.Event()
        change_handoff_ready = threading.Event()
        budget_warning_emitted = False
        observed_usage: TokenUsage | None = None
        event_lock = threading.Lock()

        def read_stdout(stream: IO[str]) -> None:
            nonlocal thread_id, parse_error
            nonlocal budget_warning_emitted, observed_usage
            with events_path.open("w", encoding="utf-8") as event_file:
                for raw_line in stream:
                    event_file.write(raw_line)
                    event_file.flush()
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        parse_error = "Codex emitted malformed JSONL output."
                        self._emit(
                            on_progress,
                            level="error",
                            event_type="output.invalid",
                            message=parse_error,
                            node_id=node_id,
                        )
                        continue
                    if not isinstance(value, dict):
                        parse_error = "Codex JSONL event was not an object."
                        continue
                    event = cast(dict[str, object], value)
                    with event_lock:
                        events.append(event)
                    event_type_value = str(event.get("type", ""))
                    item = event.get("item")
                    item_type = (
                        str(item.get("type", "")).lower().replace("_", "")
                        if isinstance(item, dict)
                        else ""
                    )
                    item_status = (
                        str(item.get("status", "")).lower()
                        if isinstance(item, dict)
                        else ""
                    )
                    if (
                        request.handoff_after_first_file_change
                        and event_type_value in {"item.completed", "item_completed"}
                        and item_type in {"filechange", "fileupdate"}
                        and item_status in {"", "completed"}
                        and self._changed_files_from_events(tuple(events))
                    ):
                        change_handoff_ready.set()
                        self._emit(
                            on_progress,
                            level="info",
                            event_type="run.change_handoff",
                            message=(
                                "The scoped file change is ready; Empy is handing it "
                                "directly to deterministic Verification."
                            ),
                            node_id=node_id,
                        )
                        self._terminate_process(process)
                    if request.fresh_token_limit is not None:
                        # Most JSONL events carry no usage at all. Avoid
                        # rescanning the complete event history for every
                        # progress line; that made long runs needlessly
                        # quadratic before the guard could even decide.
                        event_usages = TokenUsage.extract_all(
                            event,
                            default_provider=self.provider_id,
                        )
                        if event_usages:
                            observed_usage = TokenUsage.aggregate_events(
                                events,
                                default_provider=self.provider_id,
                                provider=self.provider_id,
                            )
                        usage = observed_usage
                        if usage is not None and usage.uncached_total > request.fresh_token_limit:
                            budget_exceeded.set()
                            if not budget_warning_emitted:
                                budget_warning_emitted = True
                                self._emit(
                                    on_progress,
                                    level="error",
                                    event_type="run.budget_exceeded",
                                    message=(
                                        "Codex exceeded Empy's fresh-token limit "
                                        f"({request.fresh_token_limit}); this node cannot be "
                                        "reported as successful."
                                    ),
                                    node_id=node_id,
                                )
                            self._terminate_process(process)
                    candidate = self._thread_id_from_event(event)
                    if candidate is not None:
                        thread_id = candidate
                    event_type, message, level = self._describe_event(event)
                    self._emit(
                        on_progress,
                        level=level,
                        event_type=event_type,
                        message=message,
                        node_id=node_id,
                        raw=event,
                    )

        def read_stderr(stream: IO[str]) -> None:
            with stderr_path.open("w", encoding="utf-8") as error_file:
                for raw_line in stream:
                    error_file.write(raw_line)
                    error_file.flush()
                    stderr_lines.append(raw_line)
                    message = raw_line.strip()
                    if message:
                        normalized = message.casefold()
                        if (
                            "failed to refresh available models" in normalized
                            or "codex_models_manager" in normalized
                        ):
                            self._emit(
                                on_progress,
                                level="warning",
                                event_type="provider.diagnostic",
                                message=(
                                    "Codex model-list refresh timed out; execution continued. "
                                    "This warning is not a project verification failure."
                                ),
                                node_id=node_id,
                            )
                            continue
                        self._emit(
                            on_progress,
                            level="warning",
                            event_type="process.stderr",
                            message=message,
                            node_id=node_id,
                        )

        stdout = process.stdout
        stderr = process.stderr
        stdin = process.stdin
        if stdout is None or stderr is None or stdin is None:
            self._terminate_process(process)
            with self._process_lock:
                self._active_processes.pop(process_key, None)
            self._status = "failed"
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="failed",
                started_at=started_at,
                return_code=None,
                summary="Codex process streams were unavailable.",
                error_code="launch_failed",
                error_message="Codex process did not expose stdin, stdout, and stderr.",
            )

        stdout_thread = threading.Thread(target=read_stdout, args=(stdout,), daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, args=(stderr,), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            stdin.write(request.prompt)
            if not request.prompt.endswith("\n"):
                stdin.write("\n")
            stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            stdin.close()

        deadline = self.monotonic() + request.timeout_seconds
        terminal_status: CodexNodeStatus | None = None
        while process.poll() is None:
            if self._cancel_requested.is_set():
                terminal_status = "cancelled"
                self._terminate_process(process)
                break
            if self.monotonic() >= deadline:
                terminal_status = "timed_out"
                self._terminate_process(process)
                break
            if budget_exceeded.is_set():
                terminal_status = "failed"
                self._terminate_process(process)
                break
            self.sleep(0.05)

        try:
            return_code = process.wait(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill_process(process)
            return_code = process.wait()

        stdout_thread.join(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        stderr_thread.join(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        with self._process_lock:
            self._active_processes.pop(process_key, None)

        stderr_text = "".join(stderr_lines).strip()
        final_message = (
            final_message_path.read_text(encoding="utf-8").strip()
            if final_message_path.is_file()
            else ""
        )
        changed_files = self._changed_files_from_events(tuple(events))
        usage = TokenUsage.aggregate_events(
            events,
            default_provider=self.provider_id,
            provider=self.provider_id,
        )

        if terminal_status == "cancelled":
            self._status = "cancelled"
            self._emit(
                on_progress,
                level="warning",
                event_type="run.cancelled",
                message="Codex execution was cancelled.",
                node_id=node_id,
            )
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="cancelled",
                started_at=started_at,
                return_code=return_code,
                summary=final_message or "Codex execution was cancelled.",
                error_code="cancelled",
                error_message="The user cancelled this Codex run.",
                thread_id=thread_id,
                event_count=len(events),
                changed_files=changed_files,
                usage=usage,
            )

        if terminal_status == "timed_out":
            self._status = "failed"
            message = f"Codex exceeded the {request.timeout_seconds}-second timeout."
            self._emit(
                on_progress,
                level="error",
                event_type="run.timed_out",
                message=message,
                node_id=node_id,
            )
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="timed_out",
                started_at=started_at,
                return_code=return_code,
                summary=final_message or "Codex execution timed out.",
                error_code="timeout",
                error_message=message,
                thread_id=thread_id,
                event_count=len(events),
                changed_files=changed_files,
                usage=usage,
            )

        if change_handoff_ready.is_set() and changed_files:
            self._status = "completed"
            self._emit(
                on_progress,
                level="info",
                event_type="run.completed",
                message=(
                    "Codex produced the approved file change; Empy skipped the "
                    "redundant provider summary turn and continued to Verification."
                ),
                node_id=node_id,
            )
            result = CodexNodeExecution(
                node_id=node_id,
                task_id=request.task_id,
                status="completed",
                started_at=started_at,
                finished_at=self._utc_now(),
                return_code=0,
                thread_id=thread_id,
                summary=(
                    "The scoped file change was materialized. Empy's deterministic "
                    "Verification will decide whether the objective passes."
                ),
                changed_files=changed_files,
                event_count=len(events),
                events_path=str(events_path),
                stderr_path=str(stderr_path),
                final_message_path=str(final_message_path),
                command_path=str(command_path),
                usage=usage,
            )
            result.validate()
            return result

        if budget_exceeded.is_set():
            self._status = "failed"
            limit = request.fresh_token_limit or 0
            message = (
                "Codex exceeded Empy's fresh-token limit of "
                f"{limit} tokens; the node was stopped before it could pass."
            )
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="failed",
                started_at=started_at,
                return_code=return_code,
                summary=final_message or "Codex execution exceeded its token budget.",
                error_code="budget_exceeded",
                error_message=message,
                thread_id=thread_id,
                event_count=len(events),
                changed_files=changed_files,
                usage=usage,
            )

        if parse_error is not None:
            self._status = "failed"
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="failed",
                started_at=started_at,
                return_code=return_code,
                summary=final_message or "Codex returned invalid structured output.",
                error_code="invalid_output",
                error_message=parse_error,
                thread_id=thread_id,
                event_count=len(events),
                changed_files=changed_files,
                usage=usage,
            )

        if return_code != 0:
            self._status = "failed"
            error_code, error_message = self.map_error(stderr_text, return_code)
            self._emit(
                on_progress,
                level="error",
                event_type="run.failed",
                message=error_message,
                node_id=node_id,
            )
            return self._terminal_result(
                request=request,
                node_id=node_id,
                artifact_dir=run_dir,
                status="failed",
                started_at=started_at,
                return_code=return_code,
                summary=final_message or "Codex execution failed.",
                error_code=error_code,
                error_message=error_message,
                thread_id=thread_id,
                event_count=len(events),
                changed_files=changed_files,
                usage=usage,
            )

        self._status = "completed"
        summary = final_message or "Codex completed the approved node."
        self._emit(
            on_progress,
            level="info",
            event_type="run.completed",
            message=summary,
            node_id=node_id,
        )
        result = CodexNodeExecution(
            node_id=node_id,
            task_id=request.task_id,
            status="completed",
            started_at=started_at,
            finished_at=self._utc_now(),
            return_code=0,
            thread_id=thread_id,
            summary=summary,
            changed_files=changed_files,
            event_count=len(events),
            events_path=str(events_path),
            stderr_path=str(stderr_path),
            final_message_path=str(final_message_path),
            command_path=str(command_path),
            usage=usage,
        )
        result.validate()
        return result

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._process_lock:
            processes = tuple(self._active_processes.values())
        for process in processes:
            if process.poll() is None:
                self._terminate_process(process)

    def build_command(
        self,
        request: DriverExecutionRequest,
        *,
        executable: str,
        final_message_path: str | Path,
    ) -> list[str]:
        request.validate()
        sandbox = self.sandbox_mode or (
            "workspace-write" if request.allowed_paths else "read-only"
        )
        command = [
            executable,
            "exec",
            "--json",
            "--cd",
            str(request.project.root),
            "--sandbox",
            sandbox,
        ]

        if not (request.project.root / ".git").exists():
            command.append("--skip-git-repo-check")

        command.extend(
            [
                "--ephemeral",
                "--output-last-message",
                str(final_message_path),
            ]
        )
        if request.ignore_user_config:
            command.append("--ignore-user-config")
        if request.reasoning_effort is not None:
            command.extend(
                [
                    "--config",
                    f'model_reasoning_effort="{request.reasoning_effort}"',
                ]
            )
        command.append("-")
        return command

    @staticmethod
    def map_error(stderr: str, return_code: int) -> tuple[CodexErrorCode, str]:
        lowered = stderr.lower()
        if any(item in lowered for item in ("not logged in", "sign in", "authentication", "unauthorized")):
            return (
                "authentication_required",
                "Codex authentication expired or is unavailable. Sign in with `codex login` and retry.",
            )
        if any(item in lowered for item in ("rate limit", "quota", "too many requests")):
            return "rate_limited", "Codex reached an account or rate limit. Retry after the limit resets."
        if any(
            item in lowered
            for item in (
                "in-process app-server",
                "app-server client",
                "failed to initialize",
                "could not create path aliases",
                "state_5.sqlite",
            )
        ) or "sandbox" in lowered:
            return (
                "sandbox_error",
                "Codex sandbox or app-server could not initialize in this environment. Verify host permissions or choose an allowed workspace.",
            )
        if any(item in lowered for item in ("permission denied", "operation not permitted", "access denied")):
            return "permission_denied", "Codex could not access a required project path."
        if any(item in lowered for item in ("network", "connection", "dns", "timed out connecting")):
            return "network_error", "Codex could not reach the provider service. Check the network and retry."
        detail = stderr.strip() or f"Codex exited with status {return_code}."
        return "process_failed", detail

    def _candidate_executables(self) -> tuple[str, ...]:
        candidates: list[str] = []

        def add(value: str | Path | None) -> None:
            if value is None:
                return
            normalized = str(value)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        requested = Path(self.requested_executable).expanduser()
        try:
            if requested.is_absolute() and requested.is_file():
                add(requested)
            else:
                add(shutil.which(self.requested_executable))
        except OSError:
            pass
        for candidate in self.fallback_executables:
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    add(candidate)
            except OSError:
                continue

        def translocated(value: str) -> bool:
            return "apptranslocation" in value.casefold()

        return tuple(sorted(candidates, key=translocated))

    def _resolve_executable(self) -> str | None:
        candidates = self._candidate_executables()
        return candidates[0] if candidates else None

    def _terminal_result(
        self,
        *,
        request: DriverExecutionRequest,
        node_id: str,
        artifact_dir: Path,
        status: CodexNodeStatus,
        started_at: str,
        return_code: int | None,
        summary: str,
        error_code: CodexErrorCode,
        error_message: str,
        thread_id: str | None = None,
        event_count: int = 0,
        changed_files: tuple[str, ...] = (),
        usage: TokenUsage | None = None,
    ) -> CodexNodeExecution:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        result = CodexNodeExecution(
            node_id=node_id,
            task_id=request.task_id,
            status=status,
            started_at=started_at,
            finished_at=self._utc_now(),
            return_code=return_code,
            thread_id=thread_id,
            summary=summary,
            changed_files=changed_files,
            event_count=event_count,
            events_path=str(artifact_dir / "events.jsonl"),
            stderr_path=str(artifact_dir / "stderr.log"),
            final_message_path=str(artifact_dir / "final-message.md"),
            command_path=str(artifact_dir / "command.json"),
            error_code=error_code,
            error_message=error_message,
            usage=usage,
        )
        result.validate()
        return result

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except OSError:
            process.terminate()

    def _kill_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            process.kill()

    @staticmethod
    def _thread_id_from_event(event: dict[str, object]) -> str | None:
        event_type = str(event.get("type", ""))
        if event_type != "thread.started":
            return None
        for key in ("thread_id", "threadId", "id"):
            value = event.get(key)
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _describe_event(
        event: dict[str, object],
    ) -> tuple[str, str, CodexEventLevel]:
        event_type = str(event.get("type", "codex.event"))
        if event_type == "thread.started":
            return event_type, "Codex session started.", "info"
        if event_type in {"turn.started", "task_started"}:
            return event_type, "Codex started working on the approved node.", "info"
        if event_type in {"turn.completed", "task_complete"}:
            return event_type, "Codex completed the current turn.", "info"
        if event_type in {"turn.failed", "error"}:
            return event_type, "Codex reported an execution failure.", "error"
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", "item"))
            if item_type in {"command_execution", "commandExecution"}:
                command = item.get("command")
                return event_type, f"Command activity: {command}", "info"
            if item_type in {"file_change", "fileChange"}:
                return event_type, "Codex prepared a file change.", "info"
            if item_type in {"agent_message", "agentMessage"}:
                text = str(item.get("text", "Codex produced a message."))
                return event_type, text[:500], "info"
        return event_type, event_type.replace(".", " ").replace("_", " ").title(), "info"

    @staticmethod
    def _changed_files_from_events(events: Sequence[dict[str, object]]) -> tuple[str, ...]:
        paths: set[str] = set()
        for event in events:
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).lower().replace("_", "")
            if "filechange" not in item_type and "fileupdate" not in item_type:
                continue
            for key in ("path", "file_path", "relative_path"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    paths.add(value)
            changes = item.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if isinstance(change, dict):
                        for key in ("path", "file_path", "relative_path"):
                            value = change.get(key)
                            if isinstance(value, str) and value:
                                paths.add(value)
        return tuple(sorted(paths))

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        *,
        level: CodexEventLevel,
        event_type: str,
        message: str,
        node_id: str | None,
        raw: dict[str, object] | None = None,
    ) -> None:
        if callback is None:
            return
        event = CodexProgressEvent(
            timestamp=CodexDriver._utc_now(),
            level=level,
            event_type=event_type,
            message=message,
            node_id=node_id,
            raw=raw,
        )
        event.validate()
        callback(event)

    @staticmethod
    def _driver_status_for_node(status: CodexNodeStatus) -> DriverStatus:
        mapping: dict[CodexNodeStatus, DriverStatus] = {
            "pending": "available",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "timed_out": "failed",
            "unavailable": "unavailable",
            "skipped": "cancelled",
        }
        return mapping[status]

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
