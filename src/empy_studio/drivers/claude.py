from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

from empy_studio.core import (
    DriverCapabilities,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverInspection,
    DriverStatus,
)

from .base import BaseDriver

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessFactory = Callable[..., subprocess.Popen[str]]


class ClaudeCodeDriver(BaseDriver):
    """Bounded Claude Code CLI adapter using an external environment credential."""

    def __init__(
        self,
        *,
        executable: str = "claude",
        enabled: bool = True,
        credential_environment_variable: str = "ANTHROPIC_API_KEY",
        command_runner: CommandRunner | None = None,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        if not credential_environment_variable.strip():
            raise ValueError("credential environment variable cannot be empty")
        self.requested_executable = executable
        self.enabled = enabled
        self.credential_environment_variable = credential_environment_variable
        self.command_runner = command_runner or cast(CommandRunner, subprocess.run)
        self.process_factory = process_factory or cast(ProcessFactory, subprocess.Popen)
        self._status: DriverStatus = "unavailable"
        self._installation: DriverInspection | None = None
        self._cancel_requested = threading.Event()
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None

    @property
    def provider_id(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            planning=False,
            code_editing=True,
            verification=False,
            streaming=False,
            cancellation=True,
        )

    def status(self) -> DriverStatus:
        return self._status

    def begin_run(self) -> None:
        self._cancel_requested.clear()

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        if self._installation is not None and not refresh:
            return self._installation
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
                message="Claude Code is disabled in Empy Studio settings.",
                remediation="Enable Claude Code in provider settings before running.",
            )
            inspection.validate()
            self._installation = inspection
            self._status = "unavailable"
            return inspection

        executable = shutil.which(self.requested_executable)
        if executable is None and Path(self.requested_executable).is_file():
            executable = str(Path(self.requested_executable).expanduser().resolve())
        if executable is None:
            inspection = DriverInspection(
                provider_id=self.provider_id,
                display_name=self.display_name,
                availability="missing",
                implemented=True,
                enabled=True,
                executable=None,
                version=None,
                authenticated=False,
                message="Claude Code CLI was not found on this system.",
                remediation="Install Claude Code CLI and refresh provider status.",
            )
            inspection.validate()
            self._installation = inspection
            self._status = "unavailable"
            return inspection

        try:
            version_result = self.command_runner(
                [executable, "--version"],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            inspection = DriverInspection(
                provider_id=self.provider_id,
                display_name=self.display_name,
                availability="unavailable",
                implemented=True,
                enabled=True,
                executable=executable,
                version=None,
                authenticated=False,
                message=f"Empy could not verify Claude Code CLI: {exc}",
                remediation="Check the Claude Code installation and refresh status.",
            )
            inspection.validate()
            self._installation = inspection
            self._status = "unavailable"
            return inspection

        version = (version_result.stdout or version_result.stderr).strip()
        if version_result.returncode != 0 or not version:
            inspection = DriverInspection(
                provider_id=self.provider_id,
                display_name=self.display_name,
                availability="unavailable",
                implemented=True,
                enabled=True,
                executable=executable,
                version=version or None,
                authenticated=False,
                message="Claude Code CLI version check failed.",
                remediation="Update or reinstall Claude Code CLI, then refresh status.",
            )
            inspection.validate()
            self._installation = inspection
            self._status = "unavailable"
            return inspection

        authenticated = bool(os.environ.get(self.credential_environment_variable, "").strip())
        if not authenticated:
            inspection = DriverInspection(
                provider_id=self.provider_id,
                display_name=self.display_name,
                availability="unauthenticated",
                implemented=True,
                enabled=True,
                executable=executable,
                version=version,
                authenticated=False,
                message=(
                    "Claude Code CLI is installed, but its configured credential "
                    "environment variable is empty."
                ),
                remediation=(
                    f"Set {self.credential_environment_variable} outside the project, "
                    "then refresh provider status."
                ),
            )
            inspection.validate()
            self._installation = inspection
            self._status = "unavailable"
            return inspection

        inspection = DriverInspection(
            provider_id=self.provider_id,
            display_name=self.display_name,
            availability="available",
            implemented=True,
            enabled=True,
            executable=executable,
            version=version,
            authenticated=True,
            message=(
                "Claude Code CLI and its external credential are configured. "
                "The first real run validates provider access."
            ),
        )
        inspection.validate()
        self._installation = inspection
        self._status = "available"
        return inspection

    def execute(self, request: DriverExecutionRequest) -> DriverExecutionResult:
        request.validate()
        installation = self.inspect()
        if not installation.ready or installation.executable is None:
            result = DriverExecutionResult(
                status="unavailable",
                return_code=None,
                summary=installation.message,
            )
            result.validate()
            return result

        self._status = "running"
        before_paths = self._git_paths(request.project.root)
        command = [
            installation.executable,
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--disallowedTools",
            "Bash",
            request.prompt,
        ]
        try:
            process = self.process_factory(
                command,
                cwd=request.project.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ.copy(),
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            self._status = "failed"
            result = DriverExecutionResult(
                status="failed",
                return_code=None,
                summary=f"Claude Code process could not be launched: {exc}",
            )
            result.validate()
            return result

        with self._process_lock:
            self._active_process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=request.timeout_seconds)
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                self._terminate(process)
                stdout, stderr = process.communicate()
                return_code = process.returncode
                self._status = "failed"
                result = DriverExecutionResult(
                    status="failed",
                    return_code=return_code,
                    summary=(
                        f"Claude Code exceeded the {request.timeout_seconds}-second timeout."
                    ),
                    changed_files=tuple(sorted(self._git_paths(request.project.root) - before_paths)),
                )
                result.validate()
                return result
        finally:
            with self._process_lock:
                self._active_process = None

        if self._cancel_requested.is_set():
            self._status = "cancelled"
            result = DriverExecutionResult(
                status="cancelled",
                return_code=return_code,
                summary="Claude Code execution was cancelled.",
                changed_files=tuple(sorted(self._git_paths(request.project.root) - before_paths)),
            )
            result.validate()
            return result

        raw_stdout = (stdout or "").strip()
        summary = raw_stdout
        is_error = return_code != 0
        try:
            payload = json.loads(raw_stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            is_error = is_error or bool(payload.get("is_error"))
            summary = str(payload.get("result") or payload.get("message") or raw_stdout)
        if is_error:
            self._status = "failed"
            detail = (stderr or "").strip()
            result = DriverExecutionResult(
                status="failed",
                return_code=return_code,
                summary=detail or summary or "Claude Code execution failed.",
                changed_files=tuple(sorted(self._git_paths(request.project.root) - before_paths)),
            )
            result.validate()
            return result

        self._status = "completed"
        changed_files = self._git_paths(request.project.root) - before_paths
        unauthorized = sorted(changed_files - set(request.allowed_paths))
        if unauthorized:
            self._status = "failed"
            result = DriverExecutionResult(
                status="failed",
                return_code=return_code,
                summary=(
                    "Claude Code changed files outside the approved ownership: "
                    + ", ".join(unauthorized)
                ),
                changed_files=tuple(sorted(changed_files)),
            )
            result.validate()
            return result
        result = DriverExecutionResult(
            status="completed",
            return_code=return_code,
            summary=summary or "Claude Code completed the approved task.",
            changed_files=tuple(sorted(changed_files)),
        )
        result.validate()
        return result

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._process_lock:
            process = self._active_process
        if process is not None and process.poll() is None:
            self._terminate(process)

    @staticmethod
    def _git_paths(root: Path) -> set[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "status", "--short", "--untracked-files=all"],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return set()
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            value = line[3:] if len(line) >= 3 else line
            if " -> " in value:
                value = value.rsplit(" -> ", 1)[-1]
            if value:
                paths.add(value)
        return paths

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        try:
            if os.name == "posix" and process.pid:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
