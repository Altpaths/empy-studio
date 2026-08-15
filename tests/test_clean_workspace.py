from __future__ import annotations

from pathlib import Path

from empy_studio import web_desktop


def test_clean_workspace_root_is_new_and_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    normal_root = tmp_path / "Application Support" / "Empy Studio"
    monkeypatch.setattr(web_desktop, "default_workspace_root", lambda: normal_root)

    first = web_desktop.clean_workspace_root()
    second = web_desktop.clean_workspace_root()

    assert first != second
    assert first.parent == normal_root.parent / "Empy Studio Clean"
    assert second.parent == first.parent
    assert first.is_dir()
    assert second.is_dir()
    assert not (first / "workspace.db").exists()
