from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

RunState = Literal[
    "planned",
    "running",
    "completed",
    "failed",
    "cancelled",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkspaceProject:
    project_id: str
    root: str
    project_type: str
    display_name: str
    created_at: str
    updated_at: str
    last_opened_at: str

    def validate(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id cannot be empty")
        root = Path(self.root).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        if not self.project_type.strip():
            raise ValueError("project_type cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")


@dataclass(frozen=True)
class WorkspaceTask:
    task_id: str
    project_id: str
    title: str
    request_text: str
    task_kind: str
    status: str
    contract: dict[str, Any]
    created_at: str
    updated_at: str

    def validate(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.project_id.strip():
            raise ValueError("project_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.request_text.strip():
            raise ValueError("request_text cannot be empty")
        if not self.task_kind.strip():
            raise ValueError("task_kind cannot be empty")
        if not self.status.strip():
            raise ValueError("status cannot be empty")


@dataclass(frozen=True)
class WorkspaceRun:
    run_id: str
    task_id: str
    project_id: str
    state: RunState
    driver_name: str | None
    summary: str
    evidence_path: str | None
    created_at: str
    updated_at: str

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.project_id.strip():
            raise ValueError("project_id cannot be empty")
        if self.state not in {
            "planned",
            "running",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError(f"unsupported run state: {self.state}")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
