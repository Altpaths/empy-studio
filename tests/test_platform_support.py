from __future__ import annotations

from pathlib import Path

from empy_studio.platform_support import PlatformSpec, default_workspace_root


def test_default_workspace_root_is_host_specific(tmp_path: Path, monkeypatch) -> None:
    mac = PlatformSpec("macos", "arm64", "macos-arm64", "shell")
    linux = PlatformSpec("linux", "x86_64", "linux-x86_64", "shell")
    windows = PlatformSpec("windows", "x86_64", "windows-x86_64", "powershell")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert default_workspace_root(mac) == tmp_path / "Library" / "Application Support" / "Empy Studio"
    assert default_workspace_root(linux) == tmp_path / "xdg" / "Empy Studio"
    assert default_workspace_root(windows) == tmp_path / "local" / "Empy Studio"
