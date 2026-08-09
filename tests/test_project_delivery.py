from __future__ import annotations

import zipfile
from pathlib import Path

from empy_studio.project_delivery import (
    export_project_zip,
    import_project_archive,
    import_project_folder,
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
    assert not (tmp_path / "outside.txt").exists()
