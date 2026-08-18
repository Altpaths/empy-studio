from __future__ import annotations

import os
from pathlib import Path

from empy_studio.core.project_service import DefaultProjectService
from empy_studio.dependency_bootstrap import prepare_project_dependencies


def _php_project(root: Path, *, lockfile: bool = True) -> None:
    (root / "composer.json").write_text(
        '{"name":"example/project","require":{"example/package":"1.0"},'
        '"scripts":{"test":"php tests/test.php"}}\n',
        encoding="utf-8",
    )
    if lockfile:
        (root / "composer.lock").write_text("{}\n", encoding="utf-8")
    (root / "index.php").write_text("<?php\n", encoding="utf-8")


def _fake_composer(bin_root: Path, *, exit_code: int = 0) -> None:
    executable = bin_root / "composer"
    executable.write_text(
        "#!/bin/sh\n"
        f"exit {exit_code}\n"
        if exit_code
        else "#!/bin/sh\nmkdir -p vendor\nprintf '%s\\n' '<?php' > vendor/autoload.php\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def test_prepares_composer_dependencies_in_isolated_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _php_project(project)
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    _fake_composer(bin_root)
    monkeypatch.setenv("PATH", os.pathsep.join((os.fspath(bin_root), os.defpath)))

    result = prepare_project_dependencies(DefaultProjectService().detect(project))

    assert result.status == "prepared"
    assert result.manager == "composer"
    assert result.generated_scope == "vendor/"
    assert (project / "vendor" / "autoload.php").is_file()
    assert "--no-scripts" in result.command
    assert "--no-plugins" in result.command


def test_missing_lockfile_is_an_actionable_blocker(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _php_project(project, lockfile=False)
    monkeypatch.setenv("PATH", os.fspath(tmp_path / "no-tools"))

    result = prepare_project_dependencies(DefaultProjectService().detect(project))

    assert result.status == "unavailable"
    assert result.manager == "composer"
    assert "composer.lock is missing" in result.message
    assert not (project / "vendor").exists()


def test_failed_package_manager_is_not_reported_as_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _php_project(project)
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    _fake_composer(bin_root, exit_code=9)
    monkeypatch.setenv("PATH", os.pathsep.join((os.fspath(bin_root), os.defpath)))

    result = prepare_project_dependencies(DefaultProjectService().detect(project))

    assert result.status == "failed"
    assert result.returncode == 9
    assert not (project / "vendor" / "autoload.php").exists()


def test_existing_dependencies_are_reused(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _php_project(project)
    (project / "vendor").mkdir()
    (project / "vendor" / "autoload.php").write_text("<?php\n", encoding="utf-8")
    monkeypatch.setenv("PATH", os.fspath(tmp_path / "no-tools"))

    result = prepare_project_dependencies(DefaultProjectService().detect(project))

    assert result.status == "not_needed"
    assert result.successful


def test_prepares_npm_dependencies_without_running_lifecycle_scripts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "node-project"
    project.mkdir()
    (project / "package.json").write_text(
        '{"name":"demo","scripts":{"test":"node test.js"}}\n',
        encoding="utf-8",
    )
    (project / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (project / "index.js").write_text("console.log('ok');\n", encoding="utf-8")
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    executable = bin_root / "npm"
    executable.write_text(
        "#!/bin/sh\nmkdir -p node_modules\nprintf '%s\\n' ignored > node_modules/.marker\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join((os.fspath(bin_root), os.defpath)))

    result = prepare_project_dependencies(DefaultProjectService().detect(project))

    assert result.status == "prepared"
    assert result.manager == "npm"
    assert result.generated_scope == "node_modules/"
    assert "--ignore-scripts" in result.command
    assert (project / "node_modules" / ".marker").is_file()
