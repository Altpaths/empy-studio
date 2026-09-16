from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from empy_studio.core import (
    ContextFile,
    ContextManifest,
    ContextPack,
    ContextSelection,
    ProjectBrain,
)


def _selection(root: Path, *, conflicting: bool = False) -> ContextSelection:
    content = "print('ok')\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    first = ContextFile("src/app.py", 10, ("named",), len(content), len(content), digest, False, content)
    second = ContextFile(
        "src/app.py",
        11,
        ("dependency",),
        len(content),
        len(content),
        hashlib.sha256(b"different").hexdigest() if conflicting else digest,
        False,
        content,
    )
    packs = (
        ContextPack("pack-a", "plan", "task", "one", "backend", "write", (first,), len(content), 1),
        ContextPack("pack-b", "plan", "task", "two", "quality", "verify", (second,), len(content), 1),
    )
    brain = ProjectBrain(str(root), "fixture", "python", (), None, True, True, "small fixture")
    return ContextSelection(
        schema_version=1,
        selection_id="selection",
        plan_id="plan",
        task_id="task",
        project_root=str(root),
        created_at="2026-01-01T00:00:00+00:00",
        project_brain=brain,
        packs=packs,
        exclusions=(),
        scanned_candidates=2,
        selected_files=2,
        selected_bytes=len(content) * 2,
    )


def test_manifest_deduplicates_same_file_and_produces_stable_snapshot(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    manifest = ContextManifest.from_selection(selection)
    assert len(manifest.files) == 1
    assert manifest.selected_bytes == len("print('ok')\n")
    assert manifest.snapshot_sha256 == ContextManifest.from_selection(selection).snapshot_sha256
    assert "src/app.py" in manifest.handoff(changed_files=("src/app.py",))


def test_manifest_rejects_conflicting_file_hashes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="conflicting hashes"):
        ContextManifest.from_selection(_selection(tmp_path, conflicting=True))
