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

from .base import BaseDriver

CodexAvailability = Literal[
    "available",
    "missing",
    "unauthenticated",
    "unavailable",
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
]
CodexEventLevel = Literal["info", "warning", "error"]

DEFAULT_PREFLIGHT_TIMEOUT: Final[float] = 8.0
DEFAULT_CANCEL_GRACE_SECONDS: Final[float] = 2.0


@dataclass(frozen=True)
class CodexInstallation:
    availability: CodexAvailability
    executable: str | None
    version: str | None
    authenticated: bool
    message: str
    remediation: str | None = None

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
        return asdict(self)


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
        command_runner: CommandRunner | None = None,
        process_factory: ProcessFactory | None = None,
        monotonic: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
    ) -> None:
        self.requested_executable = executable
        self.enabled = enabled
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
        self._active_process: subprocess.Popen[str] | None = None
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

    def status(self) -> DriverStatus:
        return self._status

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

        executable = self._resolve_executable()
        if executable is None:
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

        try:
            version_result = self.command_runner(
                [executable, "--version"],
                text=True,
                capture_output=True,
                timeout=DEFAULT_PREFLIGHT_TIMEOUT,
                check=False,
            )
            version = (version_result.stdout or version_result.stderr).strip()
            if version_result.returncode != 0 or not version:
                installation = CodexInstallation(
                    availability="unavailable",
                    executable=executable,
                    version=version or None,
                    authenticated=False,
                    message="Codex CLI is installed but its version check failed.",
                    remediation="Reinstall or update Codex CLI.",
                )
                installation.validate()
                self._installation = installation
                self._status = "unavailable"
                return installation

            exec_result = self.command_runner(
                [executable, "exec", "--help"],
                text=True,
                capture_output=True,
                timeout=DEFAULT_PREFLIGHT_TIMEOUT,
                check=False,
            )
            if exec_result.returncode != 0:
                installation = CodexInstallation(
                    availability="unavailable",
                    executable=executable,
                    version=version,
                    authenticated=False,
                    message="This Codex CLI installation does not provide non-interactive execution.",
                    remediation="Update Codex CLI to a version that supports `codex exec`.",
                )
                installation.validate()
                self._installation = installation
                self._status = "unavailable"
                return installation

            auth_result = self.command_runner(
                [executable, "login", "status"],
                text=True,
                capture_output=True,
                timeout=DEFAULT_PREFLIGHT_TIMEOUT,
                check=False,
            )
            if auth_result.returncode != 0:
                installation = CodexInstallation(
                    availability="unauthenticated",
                    executable=executable,
                    version=version,
                    authenticated=False,
                    message="Codex CLI is installed but is not signed in.",
                    remediation="Run `codex login` once, then retry from Empy Studio.",
                )
                installation.validate()
                self._installation = installation
                self._status = "unavailable"
                return installation
        except (OSError, subprocess.TimeoutExpired) as exc:
            installation = CodexInstallation(
                availability="unavailable",
                executable=executable,
                version=None,
                authenticated=False,
                message=f"Empy could not verify Codex CLI: {exc}",
                remediation="Check the Codex installation and try again.",
            )
            installation.validate()
            self._installation = installation
            self._status = "unavailable"
            return installation

        installation = CodexInstallation(
            availability="available",
            executable=executable,
            version=version,
            authenticated=True,
            message="Codex CLI is installed, authenticated, and ready.",
        )
        installation.validate()
        self._installation = installation
        self._status = "available"
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
                error_code=(
                    "installation_missing"
                    if installation.availability == "missing"
                    else "authentication_required"
                    if installation.availability == "unauthenticated"
                    else "launch_failed"
                ),
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
        self._cancel_requested.clear()
        self._status = "running"
        self._emit(
            on_progress,
            level="info",
            event_type="run.started",
            message=f"Starting Codex for {node_id}",
            node_id=node_id,
        )

        process_environment = os.environ.copy()
        process_environment.setdefault("NO_COLOR", "1")

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

        with self._process_lock:
            self._active_process = process

        events: list[dict[str, object]] = []
        stderr_lines: list[str] = []
        thread_id: str | None = None
        parse_error: str | None = None
        event_lock = threading.Lock()

        def read_stdout(stream: IO[str]) -> None:
            nonlocal thread_id, parse_error
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
                self._active_process = None
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
            self.sleep(0.05)

        try:
            return_code = process.wait(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill_process(process)
            return_code = process.wait()

        stdout_thread.join(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        stderr_thread.join(timeout=DEFAULT_CANCEL_GRACE_SECONDS)
        with self._process_lock:
            self._active_process = None

        stderr_text = "".join(stderr_lines).strip()
        final_message = (
            final_message_path.read_text(encoding="utf-8").strip()
            if final_message_path.is_file()
            else ""
        )
        changed_files = self._changed_files_from_events(tuple(events))

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
        )
        result.validate()
        return result

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._process_lock:
            process = self._active_process
        if process is not None and process.poll() is None:
            self._terminate_process(process)

    def build_command(
        self,
        request: DriverExecutionRequest,
        *,
        executable: str,
        final_message_path: str | Path,
    ) -> list[str]:
        request.validate()
        sandbox = "workspace-write" if request.allowed_paths else "read-only"
        return [
            executable,
            "exec",
            "--json",
            "--cd",
            str(request.project.root),
            "--sandbox",
            sandbox,
            "--output-last-message",
            str(final_message_path),
            "-",
        ]

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
        if any(item in lowered for item in ("permission denied", "operation not permitted", "access denied")):
            return "permission_denied", "Codex could not access a required project path."
        if any(item in lowered for item in ("network", "connection", "dns", "timed out connecting")):
            return "network_error", "Codex could not reach the provider service. Check the network and retry."
        if "sandbox" in lowered:
            return "sandbox_error", "Codex sandbox initialization or execution failed."
        detail = stderr.strip() or f"Codex exited with status {return_code}."
        return "process_failed", detail

    def _resolve_executable(self) -> str | None:
        requested = Path(self.requested_executable).expanduser()
        if requested.is_absolute() and requested.is_file():
            return str(requested.resolve())
        resolved = shutil.which(self.requested_executable)
        if resolved is not None:
            return resolved
        candidates = (
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            Path.home() / ".npm-global" / "bin" / "codex",
            Path.home() / ".local" / "bin" / "codex",
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        return None

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
