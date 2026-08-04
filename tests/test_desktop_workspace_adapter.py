from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    ProjectDescriptor,
)
from empy_studio.desktop.workspace_adapter import (
    DesktopWorkspaceAdapter,
)


def test_adapter_persists_project(
    tmp_path: Path,
) -> None:
    project_root = (
        tmp_path / "project"
    )
    project_root.mkdir()

    adapter = (
        DesktopWorkspaceAdapter(
            tmp_path / "workspace"
        )
    )
    project = ProjectDescriptor(
        root=project_root,
        project_type="generic",
        display_name="project",
    )

    adapter.save_project(project)

    projects = adapter.list_projects()
    assert len(projects) == 1
    assert projects[0].root == (
        project_root.resolve()
    )
