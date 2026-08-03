from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from empy_studio.uninstaller import (
    InstallState,
    UninstallerSpec,
    render_unix_uninstaller,
    render_windows_uninstaller,
    write_uninstaller,
)


def unix_spec() -> UninstallerSpec:
    return UninstallerSpec(
        product="Empy Studio",
        kind="shell",
        install_root="${HOME}/.local/share/empy-studio",
    )


def windows_spec() -> UninstallerSpec:
    return UninstallerSpec(
        product="Empy Studio",
        kind="powershell",
        install_root="$env:LOCALAPPDATA\\EmpyStudio",
    )


def test_loads_install_state(tmp_path: Path) -> None:
    path = tmp_path / "install-state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Empy Studio",
                "version": "1.0.0",
                "target": "macos-arm64",
                "package_sha256": "a" * 64,
                "version_root": "/tmp/empy/versions/1.0.0",
                "wrapper_path": "/tmp/bin/empy",
            }
        ),
        encoding="utf-8",
    )

    state = InstallState.load(path)
    assert state.version == "1.0.0"
    assert state.target == "macos-arm64"


def test_unix_uninstaller_uses_install_state() -> None:
    script = render_unix_uninstaller(unix_spec())
    assert "install-state.json" in script
    assert "version_root" in script
    assert "wrapper_path" in script
    assert "Refusing to remove path outside install root" in script


def test_unix_removes_only_owned_paths() -> None:
    script = render_unix_uninstaller(unix_spec())
    assert 'rm -rf "$version_root"' in script
    assert 'rm -f "$wrapper_path"' in script
    assert 'rm -f "$STATE_FILE"' in script
    assert "sudo" not in script


def test_windows_uninstaller_uses_install_state() -> None:
    script = render_windows_uninstaller(windows_spec())
    assert "ConvertFrom-Json" in script
    assert "version_root" in script
    assert "wrapper_path" in script
    assert "Refusing to remove path outside install root" in script


def test_windows_avoids_registry_and_admin() -> None:
    script = render_windows_uninstaller(windows_spec())
    forbidden = (
        "HKCU:",
        "HKLM:",
        "SetEnvironmentVariable",
        "RunAsAdministrator",
    )
    assert not any(value in script for value in forbidden)


def test_writes_executable_unix_uninstaller(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "uninstall.sh"
    artifact = write_uninstaller(unix_spec(), destination)

    assert destination.stat().st_mode & stat.S_IXUSR
    assert artifact.sha256 == hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()


def test_writes_windows_uninstaller_with_crlf(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "uninstall.ps1"
    artifact = write_uninstaller(windows_spec(), destination)

    assert b"\r\n" in destination.read_bytes()
    assert artifact.size_bytes > 0


def test_output_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.sh"
    second = tmp_path / "second.sh"

    write_uninstaller(unix_spec(), first)
    write_uninstaller(unix_spec(), second)

    assert first.read_bytes() == second.read_bytes()


def test_rejects_wrong_renderer_kind() -> None:
    with pytest.raises(ValueError, match="shell kind"):
        render_unix_uninstaller(windows_spec())

    with pytest.raises(ValueError, match="powershell kind"):
        render_windows_uninstaller(unix_spec())


def test_rejects_invalid_state_digest() -> None:
    with pytest.raises(ValueError, match="package_sha256"):
        InstallState(
            schema_version=1,
            product="Empy Studio",
            version="1.0.0",
            target="linux-x86_64",
            package_sha256="bad",
            version_root="/tmp/version",
            wrapper_path="/tmp/empy",
        ).validate()
