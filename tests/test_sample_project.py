from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.sample_project import copy_sample_project


def test_copy_sample_project_is_independent_and_non_destructive(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "sample-project"

    result = copy_sample_project(destination)

    assert result["status"] == "copied"
    assert result["project_type"] == "php"
    assert (destination / "composer.json").is_file()
    assert (destination / "tests" / "site-audit.php").is_file()
    (destination / "README.md").write_text("changed copy\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        copy_sample_project(destination)
