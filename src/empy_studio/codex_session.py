from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .codex_materializer import load_materialized_manifest
from .codex_workflow import CodexRunManifest, CodexRunStatus

EVIDENCE_INDEX_NAME = "index.json"
INITIAL_EVENTS_NAME = "events.jsonl"
INITIAL_STDERR_NAME = "stderr.log"
INITIAL_FINAL_MESSAGE_NAME = "final-message.md"


@dataclass(frozen=True)
class EvidenceTurn:
    sequence: int
    kind: str
    status: str
    thread_id: str | None
    returncode: int | None
    event_count: int
    events_file: str
    stderr_file: str
    final_message_file: str
    command_file: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceTurn:
        return cls(
            sequence=int(data["sequence"]),
            kind=str(data["kind"]),
            status=str(data["status"]),
            thread_id=(
                str(data["thread_id"])
                if data.get("thread_id") is not None
                else None
            ),
            returncode=(
                int(data["returncode"])
                if data.get("returncode") is not None
                else None
            ),
            event_count=int(data.get("event_count", 0)),
            events_file=str(data["events_file"]),
            stderr_file=str(data["stderr_file"]),
            final_message_file=str(data["final_message_file"]),
            command_file=(
                str(data["command_file"])
                if data.get("command_file") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceIndex:
    run_id: str
    thread_id: str | None
    turns: tuple[EvidenceTurn, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceIndex:
        raw_turns = data.get("turns", [])
        if not isinstance(raw_turns, list):
            raise TypeError("Evidence index turns must be a list")

        return cls(
            run_id=str(data["run_id"]),
            thread_id=(
                str(data["thread_id"])
                if data.get("thread_id") is not None
                else None
            ),
            turns=tuple(
                EvidenceTurn.from_dict(item)
                for item in raw_turns
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "turns": [
                turn.to_dict()
                for turn in self.turns
            ],
        }


@dataclass(frozen=True)
class CodexResumeResult:
    status: str
    run_id: str
    thread_id: str
    sequence: int
    returncode: int
    event_count: int
    evidence_index: str
    events_path: str
    stderr_path: str
    final_message_path: str
    command_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _save_manifest(
    path: Path,
    manifest: CodexRunManifest,
) -> None:
    _write_json_atomic(path, manifest.to_dict())


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


def _event_count(path: Path) -> int:
    if not path.is_file():
        return 0

    events, _ = _parse_jsonl(
        path.read_text(encoding="utf-8")
    )
    return len(events)


def _initial_turn(
    manifest: CodexRunManifest,
    evidence_dir: Path,
) -> EvidenceTurn | None:
    events = evidence_dir / INITIAL_EVENTS_NAME
    stderr = evidence_dir / INITIAL_STDERR_NAME
    final_message = evidence_dir / INITIAL_FINAL_MESSAGE_NAME
    command = evidence_dir / "command.json"

    if not any(
        path.exists()
        for path in (events, stderr, final_message, command)
    ):
        return None

    return EvidenceTurn(
        sequence=0,
        kind="initial",
        status=manifest.status,
        thread_id=manifest.thread_id,
        returncode=_optional_int(
            manifest.metadata.get("returncode")
        ),
        event_count=_event_count(events),
        events_file=str(events),
        stderr_file=str(stderr),
        final_message_file=str(final_message),
        command_file=(
            str(command)
            if command.is_file()
            else None
        ),
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def load_evidence_index(
    evidence_dir: str | Path,
) -> EvidenceIndex:
    path = (
        Path(evidence_dir).expanduser().resolve()
        / EVIDENCE_INDEX_NAME
    )
    value = json.loads(
        path.read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise TypeError(
            "Evidence index must contain a JSON object"
        )
    return EvidenceIndex.from_dict(value)


def ensure_evidence_index(
    manifest: CodexRunManifest,
) -> EvidenceIndex:
    if manifest.evidence_dir is None:
        raise ValueError("Run Manifest is missing evidence_dir")

    evidence_dir = Path(
        manifest.evidence_dir
    ).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    index_path = evidence_dir / EVIDENCE_INDEX_NAME

    if index_path.is_file():
        index = load_evidence_index(evidence_dir)
        if index.run_id != manifest.run_id:
            raise ValueError(
                "Evidence index run_id does not match Run Manifest"
            )
        return index

    initial = _initial_turn(manifest, evidence_dir)
    turns = (initial,) if initial is not None else ()
    index = EvidenceIndex(
        run_id=manifest.run_id,
        thread_id=manifest.thread_id,
        turns=turns,
    )
    _write_json_atomic(index_path, index.to_dict())
    return index


def build_codex_resume_command(
    manifest: CodexRunManifest,
    *,
    codex_executable: str = "codex",
    final_message_path: str | Path,
) -> list[str]:
    if manifest.thread_id is None:
        raise ValueError(
            "Codex run cannot be resumed without thread_id"
        )
    if manifest.policy.mode != "non_interactive":
        raise ValueError(
            "Codex resume adapter requires non_interactive mode"
        )

    command = [
        codex_executable,
        "exec",
        "--json",
        "--cd",
        manifest.project_root,
        "--sandbox",
        manifest.policy.sandbox,
        "--ask-for-approval",
        manifest.policy.approval_policy,
        "--output-last-message",
        str(final_message_path),
    ]

    if manifest.policy.model is not None:
        command.extend(
            ["--model", manifest.policy.model]
        )

    if manifest.policy.web_search:
        command.append("--search")

    if manifest.policy.ignore_user_config:
        command.append("--ignore-user-config")

    if manifest.policy.ignore_rules:
        command.append("--ignore-rules")

    if manifest.policy.reasoning_effort is not None:
        command.extend(
            [
                "--config",
                (
                    "model_reasoning_effort="
                    f'"{manifest.policy.reasoning_effort}"'
                ),
            ]
        )

    command.extend(
        [
            "resume",
            manifest.thread_id,
            "-",
        ]
    )
    return command


def _append_turn(
    evidence_dir: Path,
    index: EvidenceIndex,
    turn: EvidenceTurn,
) -> EvidenceIndex:
    updated = EvidenceIndex(
        run_id=index.run_id,
        thread_id=turn.thread_id or index.thread_id,
        turns=(*index.turns, turn),
    )
    _write_json_atomic(
        evidence_dir / EVIDENCE_INDEX_NAME,
        updated.to_dict(),
    )
    return updated


def resume_codex_run(
    manifest_path: str | Path,
    follow_up_prompt: str,
    *,
    codex_executable: str = "codex",
    environment: dict[str, str] | None = None,
) -> CodexResumeResult:
    if not follow_up_prompt.strip():
        raise ValueError(
            "follow_up_prompt cannot be empty"
        )

    path = Path(manifest_path).expanduser().resolve()
    manifest = load_materialized_manifest(path)

    if manifest.status not in {
        "completed",
        "failed",
    }:
        raise ValueError(
            "Only completed or failed Codex runs can be resumed"
        )
    if manifest.thread_id is None:
        raise ValueError(
            "Codex run cannot be resumed without thread_id"
        )
    if manifest.evidence_dir is None:
        raise ValueError(
            "Run Manifest is missing evidence_dir"
        )

    evidence_dir = Path(
        manifest.evidence_dir
    ).expanduser().resolve()
    index = ensure_evidence_index(manifest)
    sequence = (
        max(
            (turn.sequence for turn in index.turns),
            default=-1,
        )
        + 1
    )

    prefix = f"resume-{sequence:04d}"
    events_path = evidence_dir / f"{prefix}-events.jsonl"
    stderr_path = evidence_dir / f"{prefix}-stderr.log"
    final_message_path = (
        evidence_dir / f"{prefix}-final-message.md"
    )
    command_path = evidence_dir / f"{prefix}-command.json"

    command = build_codex_resume_command(
        manifest,
        codex_executable=codex_executable,
        final_message_path=final_message_path,
    )
    _write_json_atomic(
        command_path,
        {
            "argv": list(command),
            "cwd": manifest.project_root,
            "sequence": sequence,
            "kind": "resume",
        },
    )

    running = replace(
        manifest,
        status="running",
        metadata={
            **manifest.metadata,
            "resume_sequence": sequence,
        },
    )
    _save_manifest(path, running)

    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)

    try:
        completed = subprocess.run(
            command,
            input=follow_up_prompt.rstrip() + "\n",
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
        turn = EvidenceTurn(
            sequence=sequence,
            kind="resume",
            status="failed",
            thread_id=manifest.thread_id,
            returncode=None,
            event_count=0,
            events_file=str(events_path),
            stderr_file=str(stderr_path),
            final_message_file=str(final_message_path),
            command_file=str(command_path),
        )
        _append_turn(evidence_dir, index, turn)

        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": "resume_timeout",
                "timeout_seconds": (
                    running.policy.timeout_seconds
                ),
            },
        )
        _save_manifest(path, failed)
        raise RuntimeError(
            "Codex resume timed out after "
            f"{running.policy.timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": (
                    "resume_execution_error"
                ),
                "error": str(exc),
            },
        )
        _save_manifest(path, failed)
        raise RuntimeError(
            f"Unable to resume Codex: {exc}"
        ) from exc

    events_path.write_text(
        completed.stdout,
        encoding="utf-8",
    )
    stderr_path.write_text(
        completed.stderr,
        encoding="utf-8",
    )

    try:
        events, emitted_thread_id = _parse_jsonl(
            completed.stdout
        )
    except (TypeError, ValueError) as exc:
        turn = EvidenceTurn(
            sequence=sequence,
            kind="resume",
            status="failed",
            thread_id=manifest.thread_id,
            returncode=completed.returncode,
            event_count=0,
            events_file=str(events_path),
            stderr_file=str(stderr_path),
            final_message_file=str(final_message_path),
            command_file=str(command_path),
        )
        _append_turn(evidence_dir, index, turn)

        failed = replace(
            running,
            status="failed",
            metadata={
                **running.metadata,
                "failure_type": "resume_invalid_jsonl",
                "returncode": completed.returncode,
                "error": str(exc),
            },
        )
        _save_manifest(path, failed)
        raise

    thread_id = emitted_thread_id or manifest.thread_id
    status: CodexRunStatus = (
        "completed"
        if completed.returncode == 0
        else "failed"
    )

    turn = EvidenceTurn(
        sequence=sequence,
        kind="resume",
        status=status,
        thread_id=thread_id,
        returncode=completed.returncode,
        event_count=len(events),
        events_file=str(events_path),
        stderr_file=str(stderr_path),
        final_message_file=str(final_message_path),
        command_file=str(command_path),
    )
    updated_index = _append_turn(
        evidence_dir,
        index,
        turn,
    )

    finished = replace(
        running,
        status=status,
        thread_id=thread_id,
        metadata={
            **running.metadata,
            "returncode": completed.returncode,
            "event_count": len(events),
            "resume_sequence": sequence,
            "evidence_turn_count": len(
                updated_index.turns
            ),
        },
    )
    _save_manifest(path, finished)

    return CodexResumeResult(
        status=status,
        run_id=finished.run_id,
        thread_id=thread_id,
        sequence=sequence,
        returncode=completed.returncode,
        event_count=len(events),
        evidence_index=str(
            evidence_dir / EVIDENCE_INDEX_NAME
        ),
        events_path=str(events_path),
        stderr_path=str(stderr_path),
        final_message_path=str(final_message_path),
        command_path=str(command_path),
    )
