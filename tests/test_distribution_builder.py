from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.distribution_builder import (
    DistributionBuildConfig,
    build_distribution,
)
from empy_studio.distribution_manifest import (
    DistributionManifest,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


def config(
    tmp_path: Path,
) -> DistributionBuildConfig:
    return DistributionBuildConfig(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0"
        ),
        repository="Altpaths/empy-studio",
        minimum_python="3.10",
        package_url=(
            "https://github.com/Altpaths/"
            "empy-studio/releases/download/"
            "v1.0.0/empy_studio-1.0.0-"
            "py3-none-any.whl"
        ),
        package_sha256="a" * 64,
        package_filename=(
            "empy_studio-1.0.0-"
            "py3-none-any.whl"
        ),
        output_dir=str(
            tmp_path / "dist"
        ),
    )


def test_builds_all_v1_installers(
    tmp_path: Path,
) -> None:
    result = build_distribution(
        config(tmp_path)
    )

    assert result.status == "built"
    assert len(result.installer_paths) == 5
    assert len(
        result.uninstaller_paths
    ) == 2

    for value in (
        *result.installer_paths,
        *result.uninstaller_paths,
    ):
        assert Path(value).is_file()


def test_manifest_contains_all_targets(
    tmp_path: Path,
) -> None:
    result = build_distribution(
        config(tmp_path)
    )
    manifest = DistributionManifest.load(
        result.manifest_path
    )

    assert {
        asset.target
        for asset in manifest.assets
    } == {
        "macos-arm64",
        "macos-x86_64",
        "linux-arm64",
        "linux-x86_64",
        "windows-x86_64",
    }


def test_build_is_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("generation failed")

    monkeypatch.setattr(
        "empy_studio.distribution_builder."
        "write_windows_installer",
        fail,
    )

    build_config = config(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="generation failed",
    ):
        build_distribution(
            build_config
        )

    assert not (
        Path(build_config.output_dir)
        / "1.0.0"
    ).exists()


def test_refuses_existing_version_directory(
    tmp_path: Path,
) -> None:
    build_config = config(tmp_path)
    version_root = (
        Path(build_config.output_dir)
        / "1.0.0"
    )
    version_root.mkdir(
        parents=True
    )

    with pytest.raises(FileExistsError):
        build_distribution(
            build_config
        )
