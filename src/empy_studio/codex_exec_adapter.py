from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .codex_materializer import (
    load_materialized_manifest,
)
from .codex_workflow import CodexRunManifest, CodexRunStatus

EVENTS_NAME = "events.jsonl"
STDERR_NAME = "stderr.log"
FINAL_MESSAGE_NAME = "final-message.md"
COMMAND_NAME = "command.json"


@dataclass(frozen=True)
class CodexExecResult:
    status: str
    run_id: str
    returncode: int
    thread_id: str | None
    event_count: int
    events_path: str
    stderr_path: str
    final_message_path: str
    command_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "returncode": self.returncode,
            "thread_id": self.thread_id,
            "event_count": self.event_count,
            "events_path": self.events_path,
            "stderr_path": self.stderr_path,
            "final_message_path": self.final_message_path,
            "command_path": self.command_path,
        }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _save_manifest(
    manifest_path: Path,
    manifest: CodexRunManifest,
) -> None:
    _write_json_atomic(manifest_path, manifest.to_dict())


def _build_prompt(manifest: CodexRunManifest) -> str:
    if manifest.agents_file is None or manifest.prompt_file is None:
        raise ValueError("Prepared run is missing AGENTS.md or prompt file")

    agents = Path(manifest.agents_file).read_text(encoding="utf-8")
    prompt = Path(manifest.prompt_file).read_text(encoding="utf-8")

    return (
        "# Run-specific operating instructions\n\n"
        f"{agents.rstrip()}\n\n"
        "# Task prompt\n\n"
        f"{prompt.rstrip()}\n"
    )


def build_codex_exec_command(
    manifest: CodexRunManifest,
    *,
    codex_executable: str = "codex",
    final_message_path: str | Path,
) -> list[str]:
    if manifest.status != "prepared":
        raise ValueError("Only prepared Codex runs can be executed")

    policy = manifest.policy
    if policy.mode != "non_interactive":
        raise ValueError(
            "codex exec adapter requires non_interactive mode"
        )

    command = [
        codex_executable,
        "exec",
        "--json",
        "--cd",
        manifest.project_root,
        "--sandbox",
        policy.sandbox,
    ]

    if not (Path(manifest.project_root) / ".git").exists():
        command.append("--skip-git-repo-check")

    command.extend(
        [
            "--output-last-message",
            str(final_message_path),
        ]
    )

    if policy.model is not None:
        command.extend(["--model", policy.model])

    if policy.web_search:
        command.append("--search")

    if policy.ignore_user_config:
        command.append("--ignore-user-config")

    if policy.ignore_rules:
        command.append("--ignore-rules")

    if policy.reasoning_effort is not None:
        command.extend(
            [
                "--config",
                f'model_reasoning_effort="{policy.reasoning_effort}"',
            ]
        )

    command.append("-")
    return command


def _parse_jsonl(
    raw_output: str,
) -> tuple[list[dict[str, Any]], str | None]:
    events: list[dict[str, Any]] = []
    thread_id: str | None = None

    for line_number, line in enumerate(
        raw_output.splitlines(),
        start=1,
    ):
        if not line.strip():
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid Codex JSONL event at line {line_number}"
            ) from exc

        if not isinstance(event, dict):
            raise TypeError(
                f"Codex JSONL event at line {line_number} "
                "must be a JSON object"
            )

        events.append(event)

        if event.get("type") == "thread.started":
            candidate = (
                event.get("thread_id")
                or event.get("threadId")
                or event.get("id")
            )
            if candidate is not None:
                thread_id = str(candidate)

    return events, thread_id


def _redacted_command(command: Sequence[str]) -> list[str]:
    return list(command)


def execute_codex_run(
    manifest_path: str | Path,
    *,
    codex_executable: str = "codex",
    environment: dict[str, str] | None = None,
) -> CodexExecResult:
    path = Path(manifest_path).expanduser().resolve()
    manifest = load_materialized_manifest(path)

    if manifest.status != "prepared":
        raise ValueError("Only prepared Codex runs can be executed")
    if manifest.evidence_dir is None:
        raise ValueError("Prepared run is missing evidence_dir")

    evidence_dir = Path(manifest.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    events_path = evidence_dir / EVENTS_NAME
    stderr_path = evidence_dir / STDERR_NAME
    final_message_path = evidence_dir / FINAL_MESSAGE_NAME
    command_path = evidence_dir / COMMAND_NAME

    command = build_codex_exec_command(
        manifest,
        codex_executable=codex_executable,
        final_message_path=final_message_path,
    )
    _write_json_atomic(
        command_path,
        {
            "argv": _redacted_command(command),
            "cwd": manifest.project_root,
        },
    )

    running = replace(manifest, status="running")
    _save_manifest(path, running)

    prompt = _build_prompt(running)
    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=running.project_root,
            text=True,
            capture_output=True,
            timeout=running.policy.timeout_seconds,
            check=False,
            env=process_environment,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_path.write_text(
            (
                exc.stderr
                if isinstance(exc.stderr, str)
                else ""
            ),
            encoding="utf-8",
        )
        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": "timeout",
                "timeout_seconds": running.policy.timeout_seconds,
            },
        )
        _save_manifest(path, failed)
        raise RuntimeError(
            "Codex execution timed out after "
            f"{running.policy.timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": "execution_error",
                "error": str(exc),
            },
        )
        _save_manifest(path, failed)
        raise RuntimeError(
            f"Unable to execute Codex: {exc}"
        ) from exc

    events_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    try:
        events, thread_id = _parse_jsonl(completed.stdout)
    except (TypeError, ValueError) as exc:
        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": "invalid_jsonl",
                "returncode": completed.returncode,
                "error": str(exc),
            },
        )
        _save_manifest(path, failed)
        raise

    final_status: CodexRunStatus = (
        "completed"
        if completed.returncode == 0
        else "failed"
    )
    finished = replace(
        running,
        status=final_status,
        thread_id=thread_id,
        metadata={
            **running.metadata,
            "returncode": completed.returncode,
            "event_count": len(events),
        },
    )
    _save_manifest(path, finished)

    return CodexExecResult(
        status=final_status,
        run_id=finished.run_id,
        returncode=completed.returncode,
        thread_id=thread_id,
        event_count=len(events),
        events_path=str(events_path),
        stderr_path=str(stderr_path),
        final_message_path=str(final_message_path),
        command_path=str(command_path),
    )
