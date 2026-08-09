from __future__ import annotations

import os
from pathlib import Path

import pytest

from empy_studio.core.project_brain import (
    ProjectBrainIndex,
    build_load_save_project_brain_index,
    build_project_brain_index,
    load_project_brain_index,
    save_project_brain_index,
)


def test_builds_deterministic_safe_records_with_lightweight_hints(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text(
        "import os\n\nclass ProjectBrainService:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dependency.js").write_text(
        "export const secret = true;\n",
        encoding="utf-8",
    )
    (tmp_path / "bundle.min.js").write_text("function generated(){}\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00binary")

    result = build_project_brain_index(tmp_path)
    result_again = build_project_brain_index(tmp_path)

    assert result.index.to_dict() == result_again.index.to_dict()
    assert [record.relative_path for record in result.index.records] == ["src/service.py"]
    record = result.index.records[0]
    assert record.language == "python"
    assert record.sha256
    assert record.size > 0
    assert "os" in record.imports
    assert "ProjectBrainService" in record.symbols
    assert "ProjectBrainService" in record.summary


def test_php_runtime_config_and_logs_are_skipped_but_examples_are_indexed(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.php").write_text(
        "<?php return ['password' => 'secret'];\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "config.example.php").write_text(
        "<?php return ['password' => ''];\n",
        encoding="utf-8",
    )
    (tmp_path / "storage" / "logs").mkdir(parents=True)
    (tmp_path / "storage" / "logs" / "app.log").write_text(
        "runtime data\n",
        encoding="utf-8",
    )

    result = build_project_brain_index(tmp_path)
    indexed_paths = {record.relative_path for record in result.index.records}

    assert "config/config.example.php" in indexed_paths
    assert "config/config.php" not in indexed_paths
    assert "storage/logs/app.log" not in indexed_paths
    assert "config/config.php" in result.skipped_paths
    assert "storage/logs/app.log" in result.skipped_paths


def test_reuses_unchanged_records_without_rereading_and_reports_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src.py"
    source.write_text("class Stable:\n    pass\n", encoding="utf-8")
    first = build_project_brain_index(tmp_path)

    def fail_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("unchanged file content should not be read")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    second = build_project_brain_index(tmp_path, previous=first.index)

    assert second.reused_paths == ("src.py",)
    assert second.changed_paths == ()
    assert second.removed_paths == ()
    assert second.index.records == first.index.records

    monkeypatch.undo()
    source.unlink()
    third = build_project_brain_index(tmp_path, previous=second.index)

    assert third.index.records == ()
    assert third.removed_paths == ("src.py",)


def test_save_load_and_build_load_save_helpers(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    index_path = tmp_path / ".empy" / "project-brain.json"

    first = build_project_brain_index(tmp_path)
    save_project_brain_index(first.index, index_path)

    loaded = load_project_brain_index(index_path)
    assert isinstance(loaded, ProjectBrainIndex)
    assert loaded.to_dict() == first.index.to_dict()

    second = build_load_save_project_brain_index(tmp_path, index_path)
    assert second.reused_paths == ("app.py",)
    assert load_project_brain_index(index_path).to_dict() == second.index.to_dict()


def test_symlinks_and_scan_bounds_are_not_indexed(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("class B:\n    pass\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-brain-secret.py"
    outside.write_text("class Secret:\n    pass\n", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = build_project_brain_index(tmp_path, max_scan_files=1)
    indexed_paths = {record.relative_path for record in result.index.records}

    assert len(result.index.records) == 1
    assert "link.py" not in indexed_paths
    assert result.index.scan_limit_reached
