from __future__ import annotations

import hashlib
import json
from pathlib import Path

from empy_studio.done import evaluate_done
from empy_studio.release import build_release


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "docs").mkdir()
    (root / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "docs/index.md").write_text("# Docs\n", encoding="utf-8")
    (root / "README.md").write_text("# Test\n", encoding="utf-8")
    (root / "EMPY.md").write_text("# Rules\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    return root


def test_definition_of_done_without_external_tools(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = evaluate_done(root, require_clean_git=False, require_tests=False)
    assert result["status"] == "pass"


def test_missing_tool_is_reported_not_raised(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path)
    monkeypatch.setenv("PATH", "")
    result = evaluate_done(root, require_clean_git=False, require_tests=True)
    assert result["status"] == "blocked"
    assert result["failed"]


def test_release_builder_creates_verified_artifacts(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = build_release(root, output_dir="out", skip_done_check=True)
    assert result["status"] == "built"

    artifact = Path(result["artifact"])
    manifest_path = Path(result["manifest"])
    checksum_path = Path(result["checksum"])
    notes_path = Path(result["release_notes"])

    assert artifact.exists()
    assert manifest_path.exists()
    assert checksum_path.exists()
    assert notes_path.exists()

    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == expected
    assert manifest["definition_of_done"] == "skipped"
    assert expected in checksum_path.read_text(encoding="utf-8")
