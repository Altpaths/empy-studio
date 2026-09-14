from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import macos_app_entrypoint as entry


def test_installation_is_empty_then_persistent_and_reextraction_is_fresh(tmp_path, monkeypatch):
    legacy = tmp_path / "Empy Studio"
    legacy.mkdir()
    (legacy / "workspace.sqlite3").write_text("previous test history")
    monkeypatch.setattr(entry, "default_workspace_root", lambda: legacy)
    identity = SimpleNamespace(st_dev=1, st_ino=10, st_birthtime=123.5, st_mtime_ns=100)
    monkeypatch.setattr(Path, "stat", lambda self, **kwargs: identity)
    first = entry.installation_workspace(Path("/first/Empy"))
    # Stop mocking stat before interacting with the temporary real filesystem.
    monkeypatch.undo()
    assert not first.exists()
    first.mkdir(parents=True)
    (first / "workspace.sqlite3").write_text("imported project")
    monkeypatch.setattr(entry, "default_workspace_root", lambda: legacy)
    monkeypatch.setattr(Path, "stat", lambda self, **kwargs: identity)
    assert entry.installation_workspace(Path("/moved/Empy")) == first
    identity.st_ino = 11
    second = entry.installation_workspace(Path("/first/Empy"))
    assert second != first
    identity.st_ino = 10
    identity.st_birthtime = 456.5
    assert entry.installation_workspace(Path("/first/Empy")) != first
    monkeypatch.undo()
    assert not second.exists()
    assert (first / "workspace.sqlite3").read_text() == "imported project"
    assert (legacy / "workspace.sqlite3").read_text() == "previous test history"


@pytest.mark.parametrize("args", [["--workspace", "/chosen"], ["--workspace=/chosen"], ["--clean"], ["--workspace", "/chosen", "--clean"]])
def test_explicit_workspace_and_clean_are_passed_through(args, monkeypatch):
    def unexpected():
        raise AssertionError("Explicit selection must not inspect installation")
    monkeypatch.setattr(entry, "installation_workspace", unexpected)
    calls = []
    monkeypatch.setattr(entry, "desktop_main", lambda argv: calls.append(argv) or 0)
    assert entry.main(args) == 0
    assert calls == [args]


def test_default_launch_selects_installation_and_preserves_arguments(monkeypatch):
    monkeypatch.setattr(entry, "installation_workspace", lambda: Path("/data/install"))
    calls = []
    monkeypatch.setattr(entry, "desktop_main", lambda argv: calls.append(argv) or 7)
    monkeypatch.setattr(entry.sys, "argv", ["Empy", "--port", "9000"])
    assert entry.main() == 7
    assert calls == [["--workspace", "/data/install", "--start-page", "--port", "9000"]]
