from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.distribution_manifest import (
    DistributionAsset,
    DistributionManifest,
)
from empy_studio.platform_support import (
    detect_current_platform,
    parse_target,
    resolve_target,
    supported_targets,
)
from empy_studio.release_version import ReleaseVersion


def asset(target: str, name: str) -> DistributionAsset:
    spec = parse_target(target)
    return DistributionAsset.create(
        target=spec.target,
        asset_name=name,
        sha256="a" * 64,
        size_bytes=128,
        media_type="text/plain",
    )


@pytest.mark.parametrize(
    ("raw_os", "raw_arch", "expected"),
    [
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x86_64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Linux", "amd64", "linux-x86_64"),
        ("Windows", "AMD64", "windows-x86_64"),
    ],
)
def test_resolves_supported_platforms(
    raw_os: str,
    raw_arch: str,
    expected: str,
) -> None:
    assert resolve_target(raw_os, raw_arch).target == expected


def test_declares_expected_v1_targets() -> None:
    assert supported_targets() == (
        "macos-arm64",
        "macos-x86_64",
        "linux-arm64",
        "linux-x86_64",
        "windows-x86_64",
    )


def test_windows_uses_powershell() -> None:
    spec = parse_target("windows-x86_64")
    assert spec.installer_kind == "powershell"
    assert spec.executable_suffix == ".ps1"


def test_unix_targets_use_shell() -> None:
    spec = parse_target("macos-arm64")
    assert spec.installer_kind == "shell"
    assert spec.executable_suffix == ".sh"


def test_rejects_unsupported_target() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported distribution target",
    ):
        parse_target("windows-arm64")


def test_creates_distribution_manifest() -> None:
    manifest = DistributionManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        repository="Altpaths/empy-studio",
        minimum_python="3.10",
        assets=(
            asset(
                "macos-arm64",
                "install-macos-arm64.sh",
            ),
            asset(
                "windows-x86_64",
                "install-windows-x86_64.ps1",
            ),
        ),
    )

    assert manifest.release_tag == "v1.0.0"
    assert (
        manifest.asset_for_target(
            "macos-arm64"
        ).asset_name
        == "install-macos-arm64.sh"
    )


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = DistributionManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        repository="Altpaths/empy-studio",
        minimum_python="3.10",
        assets=(
            asset(
                "linux-x86_64",
                "install-linux-x86_64.sh",
            ),
        ),
    )

    path = manifest.save(tmp_path / "distribution.json")
    assert DistributionManifest.load(path) == manifest


def test_rejects_duplicate_targets() -> None:
    duplicate = asset(
        "linux-x86_64",
        "install-linux-x86_64.sh",
    )

    with pytest.raises(
        ValueError,
        match="targets must be unique",
    ):
        DistributionManifest.create(
            product="Empy Studio",
            version=ReleaseVersion.parse("1.0.0"),
            repository="Altpaths/empy-studio",
            minimum_python="3.10",
            assets=(duplicate, duplicate),
        )


def test_rejects_wrong_installer_suffix() -> None:
    with pytest.raises(
        ValueError,
        match="must end with",
    ):
        DistributionAsset.create(
            target="windows-x86_64",
            asset_name="install-windows.sh",
            sha256="a" * 64,
            size_bytes=128,
            media_type="text/plain",
        )


def test_detect_current_platform_uses_platform_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.platform_support.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "empy_studio.platform_support.platform.machine",
        lambda: "arm64",
    )
    assert detect_current_platform().target == "macos-arm64"
