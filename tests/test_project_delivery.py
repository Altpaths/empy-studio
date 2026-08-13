from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from empy_studio.project_delivery import (
    export_project_zip,
    import_project_archive,
    import_project_folder,
    safe_upload_relative_path,
    summarize_import_skips,
)


def test_folder_import_creates_isolated_clean_git_baseline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    imported = import_project_folder(source, tmp_path / "workspace")

    assert imported.project_root != source
    assert (imported.project_root / "README.md").is_file()
    assert not (imported.project_root / ".env").exists()
    assert (imported.project_root / ".git").is_dir()
    assert ".env" in imported.skipped_members
    assert imported.copied_members == 2


def test_summarize_import_skips_explains_expected_exclusions() -> None:
    summary = summarize_import_skips(
        (
            "__MACOSX/._README.md",
            "vendor/package.php",
            "logs/app.log",
            "private_html",
            "<browser-upload-skipped>",
        )
    )

    assert summary == {
        "access_or_copy": 2,
        "dependencies": 1,
        "macos_metadata": 1,
        "sensitive_or_runtime": 1,
    }


def test_import_preserves_runtime_dependencies_but_delivery_excludes_them(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "composer.json").write_text(
        '{"require":{"php":"^8.2"}}\n',
        encoding="utf-8",
    )
    (source / "vendor" / "composer").mkdir(parents=True)
    (source / "vendor" / "autoload.php").write_text(
        "<?php // generated dependency loader\n",
        encoding="utf-8",
    )
    (source / "vendor" / "composer" / "installed.php").write_text(
        "<?php return [];\n",
        encoding="utf-8",
    )
    (source / "node_modules" / "demo").mkdir(parents=True)
    (source / "node_modules" / "demo" / "index.js").write_text(
        "module.exports = true;\n",
        encoding="utf-8",
    )

    imported = import_project_folder(source, tmp_path / "workspace")

    assert (imported.project_root / "vendor" / "autoload.php").is_file()
    assert (imported.project_root / "node_modules" / "demo" / "index.js").is_file()
    assert not any("vendor" in item for item in imported.skipped_members)
    assert not any("node_modules" in item for item in imported.skipped_members)

    exported = export_project_zip(imported.project_root, tmp_path / "out")

    with zipfile.ZipFile(exported.archive_path) as archive:
        names = archive.namelist()
    assert not any("/vendor/" in name for name in names)
    assert not any("/node_modules/" in name for name in names)


def test_import_and_export_keep_runtime_config_and_logs_out_of_delivery(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "config" / "config.php").write_text(
        "<?php return ['password' => 'secret'];\n",
        encoding="utf-8",
    )
    (source / "config" / "config.example.php").write_text(
        "<?php return ['password' => ''];\n",
        encoding="utf-8",
    )
    (source / "storage" / "logs").mkdir(parents=True)
    (source / "storage" / "logs" / "app.log").write_text(
        "runtime data\n",
        encoding="utf-8",
    )
    (source / ".empy").mkdir()
    (source / ".empy" / "run.json").write_text("state\n", encoding="utf-8")
    (source / ".mypy_cache").mkdir()
    (source / ".mypy_cache" / "cache.json").write_text("cache\n", encoding="utf-8")
    (source / "previous.zip").write_bytes(b"old delivery")
    (source / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    imported = import_project_folder(source, tmp_path / "workspace")
    exported = export_project_zip(imported.project_root, tmp_path / "out")

    assert "config/config.php" in imported.skipped_members
    assert "storage/logs/app.log" in imported.skipped_members
    assert (imported.project_root / "config" / "config.example.php").is_file()
    assert not (imported.project_root / "config" / "config.php").exists()
    assert not (imported.project_root / "storage" / "logs" / "app.log").exists()
    assert not (imported.project_root / ".empy").exists()
    assert not (imported.project_root / ".mypy_cache").exists()
    assert not (imported.project_root / "previous.zip").exists()
    assert exported.verified is True
    with zipfile.ZipFile(exported.archive_path) as archive:
        names = archive.namelist()
    assert f"{imported.project_root.name}/config/config.php" not in names
    assert f"{imported.project_root.name}/storage/logs/app.log" not in names
    assert f"{imported.project_root.name}/config/config.example.php" in names


def test_archive_import_rejects_traversal_and_export_is_single_root(tmp_path: Path) -> None:
    source_archive = tmp_path / "input.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        archive.writestr("demo/README.md", "hello\n")
        archive.writestr("demo/.env", "TOKEN=secret\n")
        archive.writestr("../outside.txt", "must not escape\n")

    imported = import_project_archive(source_archive, tmp_path / "workspace")
    exported = export_project_zip(imported.project_root, tmp_path / "out")

    assert exported.verified is True
    assert exported.file_count == 1
    with zipfile.ZipFile(exported.archive_path) as archive:
        names = archive.namelist()
    assert names == [f"{imported.project_root.name}/README.md"]
    assert "../outside.txt" in imported.skipped_members
    assert imported.copied_members == 1
    assert not (tmp_path / "outside.txt").exists()


def test_import_rejects_broad_system_roots(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="system or user root"):
        import_project_folder(Path("/"), tmp_path / "workspace")


def test_browser_upload_paths_keep_project_scope() -> None:
    assert safe_upload_relative_path("src/app.py") is not None
    assert safe_upload_relative_path("../outside.py") is None
    assert safe_upload_relative_path(".env") is None
    assert safe_upload_relative_path("C:\\Users\\demo\\app.py") is None
    assert safe_upload_relative_path("/etc/passwd") is None
