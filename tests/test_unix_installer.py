from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from empy_studio.unix_installer import (
    UnixInstallerSpec,
    render_unix_installer,
    save_unix_installer_spec,
    write_unix_installer,
)


def spec(
    *,
    target: str = "macos-arm64",
) -> UnixInstallerSpec:
    return UnixInstallerSpec(
        product="Empy Studio",
        version="1.0.0",
        target=target,
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


@pytest.mark.parametrize(
    "target",
    (
        "macos-arm64",
        "macos-x86_64",
        "linux-arm64",
        "linux-x86_64",
    ),
)
def test_renders_supported_unix_targets(
    target: str,
) -> None:
    script = render_unix_installer(
        spec(target=target)
    )
    assert "#!/bin/sh" in script
    assert "set -eu" in script
    assert f"TARGET={target}" in script


def test_script_has_secure_download_and_hash_checks() -> None:
    script = render_unix_installer(spec())
    assert "--proto '=https'" in script
    assert "--tlsv1.2" in script
    assert "Package SHA-256 mismatch" in script
    assert "shasum -a 256" in script
    assert "sha256sum" in script


def test_script_installs_without_clone() -> None:
    script = render_unix_installer(spec())
    assert "git clone" not in script
    assert "-m venv" in script
    assert "-m pip install" in script
    assert '"$VERSION_ROOT/venv/bin/python" -m pip install' in script
    assert "--force-reinstall" in script
    assert "versions/$VERSION" in script


def test_script_discovers_versioned_python_interpreters() -> None:
    script = render_unix_installer(spec())
    assert "python3.12" in script
    assert "python3.11" in script
    assert "python3.10" in script
    assert "no supported Python interpreter was found" in script


def test_script_does_not_modify_shell_profiles() -> None:
    script = render_unix_installer(spec())
    forbidden = (
        ".zshrc",
        ".bashrc",
        ".profile",
        "export PATH=",
    )
    assert not any(
        value in script
        for value in forbidden
    )


def test_script_records_install_state() -> None:
    script = render_unix_installer(spec())
    assert "install-state.json" in script
    assert '"schema_version": 1' in script
    assert '"package_sha256"' in script


def test_wrapper_uses_relocatable_python_module() -> None:
    script = render_unix_installer(spec())
    assert "ENTRYPOINT_MODULE=empy_studio.cli" in script
    assert 'venv/bin/python" -m "$wrapper_module"' in script
    assert 'venv/bin/$ENTRYPOINT"' not in script
    assert "write_wrapper empy-web empy_studio.web_desktop" in script
    assert "write_wrapper empy-desktop empy_studio.desktop.shell" in script
    assert 'Web UI command: %s/empy-web' in script


def test_current_link_replacement_does_not_follow_old_version_symlink() -> None:
    script = render_unix_installer(spec())
    assert "os.path.lexists(target)" in script
    assert "target.is_symlink()" in script
    assert "os.replace(source, target)" in script
    assert 'mv -f "$temporary_link" "$CURRENT_LINK"' not in script


def test_writes_executable_installer(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "install-macos-arm64.sh"
    artifact = write_unix_installer(
        spec(),
        destination,
    )
    mode = destination.stat().st_mode
    assert mode & stat.S_IXUSR
    assert artifact.size_bytes > 0
    assert artifact.sha256 == hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()


def test_output_is_deterministic(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.sh"
    second = tmp_path / "second.sh"
    write_unix_installer(spec(), first)
    write_unix_installer(spec(), second)
    assert first.read_bytes() == second.read_bytes()


def test_rejects_windows_target() -> None:
    with pytest.raises(
        ValueError,
        match="macOS or Linux",
    ):
        UnixInstallerSpec(
            product="Empy Studio",
            version="1.0.0",
            target="windows-x86_64",
            package_url="https://example.com/package.whl",
            package_sha256="a" * 64,
            package_filename="package.whl",
            minimum_python="3.10",
        ).validate()


def test_rejects_insecure_package_url() -> None:
    original = spec()
    invalid = UnixInstallerSpec(
        **{
            **original.to_dict(),
            "package_url": "http://example.com/package.whl",
        }
    )
    with pytest.raises(
        ValueError,
        match="https",
    ):
        invalid.validate()


def test_rejects_invalid_package_digest() -> None:
    original = spec()
    invalid = UnixInstallerSpec(
        **{
            **original.to_dict(),
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
    path = save_unix_installer_spec(
        spec(),
        tmp_path / "installer-spec.json",
    )
    content = path.read_text(encoding="utf-8")
    assert '"target": "macos-arm64"' in content
    assert '"minimum_python": "3.10"' in content
