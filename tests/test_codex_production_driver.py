from __future__ import annotations

import io
import subprocess
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
    driver = CodexDriver(artifact_root=tmp_path)

    installation = driver.inspect_installation()

    assert installation.availability == "missing"
    assert installation.ready is False
    assert installation.remediation is not None


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
    assert "--ask-for-approval" not in command
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
                '{"type":"turn.completed"}\n'
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
    assert Path(result.events_path).is_file()
    assert any(event.event_type == "thread.started" for event in events)
    assert any(event.event_type == "run.completed" for event in events)


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
