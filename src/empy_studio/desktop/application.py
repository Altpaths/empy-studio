from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from empy_studio.core import AIDriver, ProjectService, WorkspaceStore


@dataclass(frozen=True)
class DesktopDependencies:
    project_service: ProjectService
    workspace_store: WorkspaceStore
    drivers: Mapping[str, AIDriver]


class DesktopApplication:
    """Provider-neutral application boundary for the future desktop shell."""

    def __init__(
        self,
        dependencies: DesktopDependencies,
    ) -> None:
        self._dependencies = dependencies

    @property
    def available_driver_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._dependencies.drivers))

    def open_project(
        self,
        project_root: str,
    ) -> str:
        project = self._dependencies.project_service.describe(project_root)
        project.validate()
        self._dependencies.workspace_store.save_project(project)
        return project.display_name
