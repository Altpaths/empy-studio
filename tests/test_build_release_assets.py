from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_release_assets import _source_package_version


def test_release_builder_reads_version_from_source_tree(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "empy-studio"\nversion = "9.8.7"\n',
        encoding="utf-8",
    )

    assert _source_package_version(tmp_path) == "9.8.7"


def test_release_builder_requires_source_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "empy-studio"\n',
        encoding="utf-8",
    )

    with pytest.raises(TypeError, match="project.version"):
        _source_package_version(tmp_path)
