from __future__ import annotations

import errno
import io
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from empy_studio.core import DriverExecutionRequest, ProjectDescriptor
from empy_studio.drivers import CodexDriver


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: str,
        stderr: str = "",
        return_code: int = 0,
        running: bool = False,
    ) -> None:
        self.pid = 999_999
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.return_code = return_code
        self.running = running
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        if self.running and not (self.terminated or self.killed):
            return None
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False


def ready_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    del kwargs
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, stdout="codex-cli 1.2.3\n", stderr="")
    if command[-2:] == ["exec", "--help"]:
        return subprocess.CompletedProcess(command, 0, stdout="Usage: codex exec\n", stderr="")
    if command[-2:] == ["login", "status"]:
        return subprocess.CompletedProcess(command, 0, stdout="Logged in\n", stderr="")
    raise AssertionError(command)


def request(tmp_path: Path, *, timeout_seconds: int = 30) -> DriverExecutionRequest:
    return DriverExecutionRequest(
        project=ProjectDescriptor(
            root=tmp_path,
            project_type="python",
            display_name="Demo",
        ),
        task_id="task:step",
        prompt="Implement the approved step.",
        allowed_paths=("src/example.py",),
        timeout_seconds=timeout_seconds,
    )


def test_missing_installation_has_clear_remediation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("empy_studio.drivers.codex.shutil.which", lambda value: None)
    driver = CodexDriver(artifact_root=tmp_path, fallback_executables=())

    installation = driver.inspect_installation()

    assert installation.availability == "missing"
    assert installation.ready is False
    assert installation.remediation is not None


def test_maps_codex_app_server_initialization_failure_to_sandbox_error() -> None:
    code, message = CodexDriver.map_error(
        "failed to initialize in-process app-server client: Operation not permitted",
        1,
    )

    assert code == "sandbox_error"
    assert "host permissions" in message


def test_preflight_rejects_known_host_path_alias_failure_without_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def host_warning_runner(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        warning = "WARNING: could not create PATH aliases: Operation not permitted"
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="codex-cli 1.2.3\n",
                stderr=warning,
            )
        if command[-2:] == ["exec", "--help"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Usage: codex exec\n",
                stderr=warning,
            )
        if command[-2:] == ["login", "status"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Logged in\n",
                stderr=warning,
            )
        raise AssertionError(command)

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=host_warning_runner,
    )

    installation = driver.inspect_installation()

    assert installation.availability == "unavailable"
    assert installation.authenticated is True
    assert installation.error_code == "sandbox_error"
    assert "PATH aliases" in installation.message
    assert installation.remediation is not None


def test_keeps_plain_project_permission_failures_distinct() -> None:
    code, _message = CodexDriver.map_error(
        "permission denied: /workspace/src/app.py",
        1,
    )

    assert code == "permission_denied"


def test_detects_authenticated_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )
    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
    )

    installation = driver.inspect_installation()

    assert installation.ready is True
    assert installation.executable == "/usr/local/bin/codex"
    assert installation.version == "codex-cli 1.2.3"


def test_preflight_restores_cli_runtime_path_for_gui_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable = tmp_path / "codex"
    stable.write_text("#!/bin/sh\n", encoding="utf-8")
    stable.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    observed_paths: list[str] = []

    def runner(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed_paths.append(str(kwargs["env"]["PATH"]))
        return ready_runner(command, **kwargs)

    driver = CodexDriver(
        artifact_root=tmp_path / "artifacts",
        fallback_executables=(stable,),
        command_runner=runner,
    )

    installation = driver.inspect_installation()

    assert installation.ready is True
    assert observed_paths
    assert str(tmp_path) in observed_paths[0].split(os.pathsep)


def test_real_codex_preflight_works_with_a_sparse_gui_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed npm Codex shim must work without a shell PATH."""
    if not Path("/opt/homebrew/bin/codex").is_file():
        pytest.skip("Homebrew Codex is not installed on this host")

    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    installation = CodexDriver().inspect_installation(refresh=True)

    assert installation.ready is True, installation.to_dict()


def test_preflight_falls_back_from_translocated_codex_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translocated = "/System/Volumes/Data/private/var/AppTranslocation/codex"
    stable = tmp_path / "codex"
    stable.write_text("#!/bin/sh\n", encoding="utf-8")
    stable.chmod(0o755)
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: translocated,
    )

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        if command[0] == translocated:
            raise OSError(errno.ERANGE, "Result too large", translocated)
        return ready_runner(command)

    driver = CodexDriver(
        artifact_root=tmp_path / "artifacts",
        command_runner=runner,
        fallback_executables=(stable,),
    )

    installation = driver.inspect_installation()

    assert installation.ready is True
    assert installation.executable == str(stable)


def test_preflight_os_error_is_safe_when_no_fallback_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translocated = "/System/Volumes/Data/private/var/AppTranslocation/codex"
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: translocated,
    )

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        raise OSError(errno.ERANGE, "Result too large", translocated)

    installation = CodexDriver(
        command_runner=runner,
        fallback_executables=(),
    ).inspect_installation()

    assert installation.ready is False
    assert "AppTranslocation" not in installation.message
    assert "temporary macOS" in installation.message


def test_build_command_uses_read_only_without_owned_paths(tmp_path: Path) -> None:
    driver = CodexDriver(artifact_root=tmp_path)
    read_only = request(tmp_path)
    read_only = DriverExecutionRequest(
        project=read_only.project,
        task_id=read_only.task_id,
        prompt=read_only.prompt,
        allowed_paths=(),
        timeout_seconds=30,
    )

    command = driver.build_command(
        read_only,
        executable="/usr/local/bin/codex",
        final_message_path=tmp_path / "final.md",
    )

    assert command[:3] == ["/usr/local/bin/codex", "exec", "--json"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--ask-for-approval" not in command
    assert "--skip-git-repo-check" in command
    assert command[-1] == "-"


def test_build_command_allows_explicit_host_sandbox_override(tmp_path: Path) -> None:
    driver = CodexDriver(artifact_root=tmp_path, sandbox_mode="danger-full-access")
    command = driver.build_command(
        request(tmp_path),
        executable="/usr/local/bin/codex",
        final_message_path=tmp_path / "final.md",
    )

    assert command[command.index("--sandbox") + 1] == "danger-full-access"


def test_build_command_uses_bounded_runtime_configuration(tmp_path: Path) -> None:
    driver = CodexDriver(artifact_root=tmp_path)
    bounded = DriverExecutionRequest(
        project=request(tmp_path).project,
        task_id="task:bounded",
        prompt="Do bounded work.",
        allowed_paths=("src/example.py",),
        timeout_seconds=30,
        fresh_token_limit=20_000,
        reasoning_effort="low",
    )

    command = driver.build_command(
        bounded,
        executable="/usr/local/bin/codex",
        final_message_path=tmp_path / "final.md",
    )

    assert "--ignore-user-config" in command
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="low"'
    assert command[-1] == "-"


def test_streams_json_events_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text("Node completed", encoding="utf-8")
        return FakeProcess(
            stdout=(
                '{"type":"thread.started","thread_id":"thread-11"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":12,'
                '"output_tokens":5,"cached_input_tokens":3,"total_tokens":17}}\n'
            )
        )

    events = []
    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    result = driver.execute_streaming(
        request(tmp_path),
        node_id="node-step-1",
        artifact_dir=tmp_path / "run" / "node-step-1",
        on_progress=events.append,
    )

    assert result.status == "completed"
    assert result.thread_id == "thread-11"
    assert result.summary == "Node completed"
    assert result.event_count == 2
    assert result.usage is not None
    assert result.usage.input == 12
    assert result.usage.output == 5
    assert result.usage.cached == 3
    assert result.usage.total == 17
    assert result.usage.source == "provider"
    assert result.usage.provider == "codex"
    assert Path(result.events_path).is_file()
    assert any(event.event_type == "thread.started" for event in events)
    assert any(event.event_type == "run.completed" for event in events)


def test_rejects_final_turn_accounting_overage_after_process_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text("Stopped by budget", encoding="utf-8")
        return FakeProcess(
            stdout=(
                '{"type":"thread.started","thread_id":"thread-budget"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":60,'
                '"output_tokens":5,"cached_input_tokens":0,"total_tokens":65}}\n'
            )
        )

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    bounded = replace(request(tmp_path), fresh_token_limit=50)
    result = driver.execute_streaming(
        bounded,
        node_id="node-budget",
        artifact_dir=tmp_path / "run" / "node-budget",
    )

    assert result.status == "failed"
    assert result.error_code == "budget_exceeded"
    assert result.usage is not None
    assert result.usage.uncached_total == 65


def test_counts_codex_total_usage_snapshot_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text("Completed", encoding="utf-8")
        return FakeProcess(
            stdout=(
                '{"type":"event_msg","payload":{"total_token_usage":'
                '{"input_tokens":18000,"output_tokens":1000,"cached_input_tokens":12000,"total_tokens":19000},'
                '"last_token_usage":{"input_tokens":18000,"output_tokens":1000,"cached_input_tokens":12000,"total_tokens":19000}}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":18000,"output_tokens":1000,'
                '"cached_input_tokens":12000,"total_tokens":19000}}\n'
            )
        )

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    result = driver.execute_streaming(
        replace(request(tmp_path), fresh_token_limit=8_000),
        node_id="node-cumulative-usage",
        artifact_dir=tmp_path / "run" / "node-cumulative-usage",
    )

    assert result.status == "completed"
    assert result.error_code is None
    assert result.usage is not None
    assert result.usage.input == 18_000
    assert result.usage.output == 1_000
    assert result.usage.cached == 12_000
    assert result.usage.uncached_total == 7_000


def test_stops_a_follow_up_turn_after_final_accounting_overage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text("Stopped during follow-up", encoding="utf-8")
        return FakeProcess(
            running=True,
            stdout=(
                '{"type":"turn.completed","usage":{"input_tokens":60,'
                '"output_tokens":5,"cached_input_tokens":0,"total_tokens":65}}\n'
                '{"type":"turn.started"}\n'
                '{"type":"item.started"}\n'
            )
        )

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    result = driver.execute_streaming(
        replace(request(tmp_path), fresh_token_limit=50),
        node_id="node-budget-follow-up",
        artifact_dir=tmp_path / "run" / "node-budget-follow-up",
    )

    assert result.status == "failed"
    assert result.error_code == "budget_exceeded"


def test_single_file_change_hands_off_before_redundant_summary_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        return FakeProcess(
            stdout=(
                '{"type":"thread.started","thread_id":"thread-change"}\n'
                '{"type":"item.completed","item":{"type":"file_change",'
                '"status":"completed","changes":[{"path":"README.md",'
                '"kind":"update"}]}}\n'
            )
        )

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    bounded = replace(
        request(tmp_path),
        fresh_token_limit=40_000,
        handoff_after_first_file_change=True,
    )
    result = driver.execute_streaming(
        bounded,
        node_id="node-single-file",
        artifact_dir=tmp_path / "run" / "node-single-file",
    )

    assert result.status == "completed"
    assert result.error_code is None
    assert result.changed_files == ("README.md",)
    assert "deterministic Verification" in result.summary


def test_streaming_succeeds_when_usage_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del kwargs
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text("No usage emitted", encoding="utf-8")
        return FakeProcess(stdout='{"type":"turn.completed"}\n')

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )

    result = driver.execute_streaming(
        request(tmp_path),
        node_id="node-step-1",
        artifact_dir=tmp_path / "run",
    )

    assert result.status == "completed"
    assert result.usage is None


def test_nonzero_exit_maps_authentication_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        del command, kwargs
        return FakeProcess(
            stdout='{"type":"turn.failed"}\n',
            stderr="Not logged in. Run codex login.\n",
            return_code=1,
        )

    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=process_factory,
    )
    result = driver.execute_streaming(
        request(tmp_path),
        node_id="node-step-1",
        artifact_dir=tmp_path / "run",
    )

    assert result.status == "failed"
    assert result.error_code == "authentication_required"
    assert "codex login" in (result.error_message or "")


def test_timeout_terminates_active_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.drivers.codex.shutil.which",
        lambda value: "/usr/local/bin/codex",
    )
    process = FakeProcess(stdout="", running=True)
    ticks = iter((0.0, 2.0, 2.0, 2.0))
    driver = CodexDriver(
        artifact_root=tmp_path,
        command_runner=ready_runner,
        process_factory=lambda *args, **kwargs: process,
        monotonic=lambda: next(ticks),
        sleep=lambda seconds: None,
    )
    monkeypatch.setattr(driver, "_terminate_process", lambda item: item.terminate())

    result = driver.execute_streaming(
        request(tmp_path, timeout_seconds=1),
        node_id="node-step-1",
        artifact_dir=tmp_path / "run",
    )

    assert result.status == "timed_out"
    assert result.error_code == "timeout"
    assert process.terminated is True


def test_real_subprocess_contract_with_fake_codex_cli(tmp_path: Path) -> None:
    executable = tmp_path / "codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 1.2.3")
    raise SystemExit(0)
if args == ["exec", "--help"]:
    print("Usage: codex exec")
    raise SystemExit(0)
if args == ["login", "status"]:
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if args and args[0] == "exec":
    prompt = sys.stdin.read()
    if "approved step" not in prompt:
        print("missing prompt", file=sys.stderr)
        raise SystemExit(2)
    output_index = args.index("--output-last-message") + 1
    pathlib.Path(args[output_index]).write_text("Fake Codex completed", encoding="utf-8")
    print(json.dumps({"type": "thread.started", "thread_id": "thread-real"}))
    print(json.dumps({"type": "turn.completed"}))
    raise SystemExit(0)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    driver = CodexDriver(
        executable=str(executable),
        artifact_root=tmp_path / "artifacts",
    )

    result = driver.execute_streaming(
        request(tmp_path),
        node_id="node-real",
        artifact_dir=tmp_path / "artifacts" / "node-real",
    )

    assert result.status == "completed"
    assert result.thread_id == "thread-real"
    assert result.summary == "Fake Codex completed"
    assert Path(result.command_path).is_file()
