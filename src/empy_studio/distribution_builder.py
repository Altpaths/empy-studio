from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .distribution_manifest import (
    DistributionAsset,
    DistributionManifest,
)
from .release_version import ReleaseVersion
from .uninstaller import (
    UninstallerSpec,
    write_uninstaller,
)
from .unix_installer import (
    UnixInstallerSpec,
    UnixTarget,
    write_unix_installer,
)
from .windows_installer import (
    WindowsInstallerSpec,
    write_windows_installer,
)


@dataclass(frozen=True)
class DistributionBuildConfig:
    product: str
    version: ReleaseVersion
    repository: str
    minimum_python: str
    package_url: str
    package_sha256: str
    package_filename: str
    output_dir: str
    entrypoint: str = "empy"

    def validate(self) -> None:
        if not self.product.strip():
            raise ValueError("Product cannot be empty")
        if not self.repository.strip():
            raise ValueError("Repository cannot be empty")
        if not self.package_url.startswith(
            ("https://", "file://")
        ):
            raise ValueError(
                "Package URL must use https:// or file://"
            )
        if len(self.package_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.package_sha256.lower()
        ):
            raise ValueError(
                "Package SHA-256 must be a "
                "64-character hexadecimal digest"
            )
        if not self.package_filename.endswith(
            (".whl", ".zip")
        ):
            raise ValueError(
                "Package filename must be a wheel or ZIP"
            )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> DistributionBuildConfig:
        config = cls(
            product=str(data["product"]),
            version=ReleaseVersion.parse(
                str(data["version"])
            ),
            repository=str(data["repository"]),
            minimum_python=str(
                data["minimum_python"]
            ),
            package_url=str(data["package_url"]),
            package_sha256=str(
                data["package_sha256"]
            ),
            package_filename=str(
                data["package_filename"]
            ),
            output_dir=str(data["output_dir"]),
            entrypoint=str(
                data.get("entrypoint", "empy")
            ),
        )
        config.validate()
        return config

    @classmethod
    def load(
        cls,
        source: str | Path,
    ) -> DistributionBuildConfig:
        path = Path(source).expanduser().resolve()
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError(
                "Distribution build config must "
                "contain a JSON object"
            )
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["version"] = str(self.version)
        return value


@dataclass(frozen=True)
class DistributionBuildResult:
    status: str
    output_dir: str
    manifest_path: str
    installer_paths: tuple[str, ...]
    uninstaller_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _media_type(path: Path) -> str:
    if path.suffix == ".ps1":
        return "text/plain"
    if path.suffix == ".sh":
        return "text/x-shellscript"
    return "application/octet-stream"


def build_distribution(
    config: DistributionBuildConfig,
) -> DistributionBuildResult:
    config.validate()

    root = Path(
        config.output_dir
    ).expanduser().resolve()
    version_root = root / str(config.version)

    if version_root.exists():
        raise FileExistsError(version_root)

    version_root.mkdir(
        parents=True,
        exist_ok=False,
    )

    installer_assets: list[
        DistributionAsset
    ] = []
    installer_paths: list[str] = []
    uninstaller_paths: list[str] = []

    unix_targets: tuple[UnixTarget, ...] = (
        "macos-arm64",
        "macos-x86_64",
        "linux-arm64",
        "linux-x86_64",
    )

    try:
        for target in unix_targets:
            filename = f"install-{target}.sh"
            destination = version_root / filename

            artifact = write_unix_installer(
                UnixInstallerSpec(
                    product=config.product,
                    version=str(config.version),
                    target=target,
                    package_url=config.package_url,
                    package_sha256=(
                        config.package_sha256
                    ),
                    package_filename=(
                        config.package_filename
                    ),
                    minimum_python=(
                        config.minimum_python
                    ),
                    entrypoint=config.entrypoint,
                ),
                destination,
            )

            installer_assets.append(
                DistributionAsset.create(
                    target=target,
                    asset_name=filename,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    media_type=_media_type(
                        destination
                    ),
                )
            )
            installer_paths.append(
                str(destination)
            )

        windows_filename = (
            "install-windows-x86_64.ps1"
        )
        windows_destination = (
            version_root / windows_filename
        )
        windows_artifact = (
            write_windows_installer(
                WindowsInstallerSpec(
                    product=config.product,
                    version=str(config.version),
                    target="windows-x86_64",
                    package_url=config.package_url,
                    package_sha256=(
                        config.package_sha256
                    ),
                    package_filename=(
                        config.package_filename
                    ),
                    minimum_python=(
                        config.minimum_python
                    ),
                    entrypoint=config.entrypoint,
                ),
                windows_destination,
            )
        )

        installer_assets.append(
            DistributionAsset.create(
                target="windows-x86_64",
                asset_name=windows_filename,
                sha256=windows_artifact.sha256,
                size_bytes=(
                    windows_artifact.size_bytes
                ),
                media_type=_media_type(
                    windows_destination
                ),
            )
        )
        installer_paths.append(
            str(windows_destination)
        )

        unix_uninstaller = (
            version_root / "uninstall.sh"
        )
        write_uninstaller(
            UninstallerSpec(
                product=config.product,
                kind="shell",
                install_root=(
                    "${HOME}/.local/share/"
                    "empy-studio"
                ),
            ),
            unix_uninstaller,
        )
        uninstaller_paths.append(
            str(unix_uninstaller)
        )

        windows_uninstaller = (
            version_root / "uninstall.ps1"
        )
        write_uninstaller(
            UninstallerSpec(
                product=config.product,
                kind="powershell",
                install_root=(
                    "$env:LOCALAPPDATA\\"
                    "EmpyStudio"
                ),
            ),
            windows_uninstaller,
        )
        uninstaller_paths.append(
            str(windows_uninstaller)
        )

        manifest = (
            DistributionManifest.create(
                product=config.product,
                version=config.version,
                repository=config.repository,
                minimum_python=(
                    config.minimum_python
                ),
                assets=tuple(
                    installer_assets
                ),
            )
        )
        manifest_path = manifest.save(
            version_root
            / "distribution-manifest.json"
        )

        return DistributionBuildResult(
            status="built",
            output_dir=str(version_root),
            manifest_path=str(manifest_path),
            installer_paths=tuple(
                installer_paths
            ),
            uninstaller_paths=tuple(
                uninstaller_paths
            ),
        )

    except Exception:
        import shutil

        shutil.rmtree(
            version_root,
            ignore_errors=True,
        )
        raise
