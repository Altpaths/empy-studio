from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from empy_studio.windows_installer import (
    WindowsInstallerSpec,
    render_windows_installer,
    save_windows_installer_spec,
    write_windows_installer,
)


def spec() -> WindowsInstallerSpec:
    return WindowsInstallerSpec(
        product="Empy Studio",
        version="1.0.0",
        target="windows-x86_64",
        package_url=(
            "https://github.com/Altpaths/"
            "empy-studio/releases/download/"
            "v1.0.0/empy_studio-1.0.0-py3-none-any.whl"
        ),
        package_sha256="a" * 64,
        package_filename=(
            "empy_studio-1.0.0-py3-none-any.whl"
        ),
        minimum_python="3.10",
    )


def test_renders_powershell_installer() -> None:
    script = render_windows_installer(spec())
    assert "#requires -Version 5.1" in script
    assert '$ErrorActionPreference = "Stop"' in script
    assert "$Target = 'windows-x86_64'" in script


def test_installer_checks_platform_and_python() -> None:
    script = render_windows_installer(spec())
    assert "Is64BitOperatingSystem" in script
    assert "PROCESSOR_ARCHITECTURE" in script
    assert "Python $MinimumPython or newer is required" in script


def test_installer_uses_secure_download_and_hash() -> None:
    script = render_windows_installer(spec())
    assert "SecurityProtocol" in script
    assert "Tls12" in script
    assert "Invoke-WebRequest" in script
    assert "Get-FileHash" in script
    assert "Package SHA-256 mismatch" in script


def test_installer_uses_venv_without_clone() -> None:
    script = render_windows_installer(spec())
    assert "git clone" not in script
    assert '"-m",' in script
    assert '"venv",' in script
    assert "-m pip install" in script


def test_installer_does_not_modify_registry_or_path() -> None:
    script = render_windows_installer(spec())
    forbidden = (
        "SetEnvironmentVariable",
        "HKCU:",
        "HKLM:",
        "setx ",
    )
    assert not any(value in script for value in forbidden)


def test_installer_records_state_and_wrapper() -> None:
    script = render_windows_installer(spec())
    assert "install-state.json" in script
    assert "current.json" in script
    assert "$Entrypoint.cmd" in script
    assert "schema_version = 1" in script


def test_writes_deterministic_installer(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.ps1"
    second = tmp_path / "second.ps1"

    artifact = write_windows_installer(spec(), first)
    write_windows_installer(spec(), second)

    assert first.read_bytes() == second.read_bytes()
    assert artifact.sha256 == hashlib.sha256(
        first.read_bytes()
    ).hexdigest()
    assert artifact.size_bytes > 0


def test_output_uses_windows_line_endings(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "install-windows-x86_64.ps1"
    write_windows_installer(spec(), destination)
    assert b"\r\n" in destination.read_bytes()


def test_rejects_non_windows_target() -> None:
    invalid = WindowsInstallerSpec(
        **{
            **spec().to_dict(),
            "target": "macos-arm64",
        }
    )
    with pytest.raises(
        ValueError,
        match="must be Windows",
    ):
        invalid.validate()


def test_rejects_insecure_url() -> None:
    invalid = WindowsInstallerSpec(
        **{
            **spec().to_dict(),
            "package_url": "http://example.com/package.whl",
        }
    )
    with pytest.raises(
        ValueError,
        match="https",
    ):
        invalid.validate()


def test_rejects_invalid_sha256() -> None:
    invalid = WindowsInstallerSpec(
        **{
            **spec().to_dict(),
            "package_sha256": "bad",
        }
    )
    with pytest.raises(
        ValueError,
        match="SHA-256",
    ):
        invalid.validate()


def test_saves_installer_spec(
    tmp_path: Path,
) -> None:
    path = save_windows_installer_spec(
        spec(),
        tmp_path / "windows-installer.json",
    )
    content = path.read_text(encoding="utf-8")
    assert '"target": "windows-x86_64"' in content
    assert '"minimum_python": "3.10"' in content
