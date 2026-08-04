from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

DriverStatus = Literal[
    "available",
    "unavailable",
    "running",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class ProjectDescriptor:
    root: Path
    project_type: str
    display_name: str

    def validate(self) -> None:
        resolved = self.root.expanduser().resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(resolved)
        if not self.project_type.strip():
            raise ValueError("project_type cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")


@dataclass(frozen=True)
class DriverCapabilities:
    planning: bool
    code_editing: bool
    verification: bool
    streaming: bool
    cancellation: bool


@dataclass(frozen=True)
class DriverExecutionRequest:
    project: ProjectDescriptor
    task_id: str
    prompt: str
    allowed_paths: tuple[str, ...]
    timeout_seconds: int

    def validate(self) -> None:
        self.project.validate()
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.prompt.strip():
            raise ValueError("prompt cannot be empty")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        for item in self.allowed_paths:
            path = Path(item)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("allowed_paths must be safe relative paths")


@dataclass(frozen=True)
class DriverExecutionResult:
    status: DriverStatus
    return_code: int | None
    summary: str
    changed_files: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.status not in {
            "available",
            "unavailable",
            "running",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError(f"unsupported driver status: {self.status}")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if self.status == "completed" and self.return_code != 0:
            raise ValueError("completed result must have return_code 0")


class AIDriver(Protocol):
    @property
    def name(self) -> str:
        ...

    def capabilities(self) -> DriverCapabilities:
        ...

    def status(self) -> DriverStatus:
        ...

    def execute(
        self,
        request: DriverExecutionRequest,
    ) -> DriverExecutionResult:
        ...

    def cancel(self) -> None:
        ...


class ProjectService(Protocol):
    def describe(
        self,
        project_root: str | Path,
    ) -> ProjectDescriptor:
        ...


class WorkspaceStore(Protocol):
    def save_project(
        self,
        project: ProjectDescriptor,
    ) -> None:
        ...

    def list_projects(
        self,
    ) -> Sequence[ProjectDescriptor]:
        ...
