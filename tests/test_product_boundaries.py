from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.architecture_guard import (
    inspect_architecture_boundaries,
)
from empy_studio.core import (
    DriverExecutionRequest,
    ProjectDescriptor,
)


def test_current_product_boundaries_are_clean() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "empy_studio"
    )
    assert inspect_architecture_boundaries(root) == ()


def test_driver_request_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    project = ProjectDescriptor(
        root=tmp_path,
        project_type="python",
        display_name="Example",
    )
    request = DriverExecutionRequest(
        project=project,
        task_id="task-1",
        prompt="Do the work",
        allowed_paths=("../secret",),
        timeout_seconds=60,
    )

    with pytest.raises(
        ValueError,
        match="safe relative paths",
    ):
        request.validate()


def test_project_descriptor_requires_real_directory(
    tmp_path: Path,
) -> None:
    project = ProjectDescriptor(
        root=tmp_path / "missing",
        project_type="python",
        display_name="Example",
    )

    with pytest.raises(NotADirectoryError):
        project.validate()
