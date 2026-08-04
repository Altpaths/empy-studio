from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
)


def test_detects_laravel(
    tmp_path: Path,
) -> None:
    (tmp_path / "artisan").write_text(
        "#!/usr/bin/env php\n",
        encoding="utf-8",
    )
    (tmp_path / "composer.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (tmp_path / "routes").mkdir()
    (
        tmp_path
        / "routes"
        / "web.php"
    ).write_text(
        "<?php\n",
        encoding="utf-8",
    )
    (tmp_path / "resources").mkdir()

    result = (
        DefaultProjectService()
        .detect(tmp_path)
    )

    assert (
        result.descriptor.project_type
        == "laravel"
    )
    assert "artisan" in result.markers


def test_detects_python(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "pyproject.toml"
    ).write_text(
        "[project]\nname='demo'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    result = (
        DefaultProjectService()
        .detect(tmp_path)
    )

    assert (
        result.descriptor.project_type
        == "python"
    )
    assert result.has_tests


def test_detects_node_package_manager(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "package.json"
    ).write_text(
        "{}\n",
        encoding="utf-8",
    )
    (
        tmp_path
        / "pnpm-lock.yaml"
    ).write_text(
        "lockfileVersion: 9\n",
        encoding="utf-8",
    )

    result = (
        DefaultProjectService()
        .detect(tmp_path)
    )

    assert (
        result.descriptor.project_type
        == "node"
    )
    assert (
        result.package_manager
        == "pnpm"
    )


def test_generic_project_is_allowed(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "README.md"
    ).write_text(
        "# Demo\n",
        encoding="utf-8",
    )

    result = (
        DefaultProjectService()
        .detect(tmp_path)
    )

    assert (
        result.descriptor.project_type
        == "generic"
    )
