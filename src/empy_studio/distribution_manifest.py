from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .platform_support import (
    DistributionTarget,
    InstallerKind,
    parse_target,
)
from .release_version import ReleaseVersion


@dataclass(frozen=True)
class DistributionAsset:
    target: DistributionTarget
    installer_kind: InstallerKind
    asset_name: str
    sha256: str
    size_bytes: int
    media_type: str

    @classmethod
    def create(
        cls,
        *,
        target: DistributionTarget,
        asset_name: str,
        sha256: str,
        size_bytes: int,
        media_type: str,
    ) -> DistributionAsset:
        spec = parse_target(target)
        asset = cls(
            target=target,
            installer_kind=spec.installer_kind,
            asset_name=asset_name,
            sha256=sha256,
            size_bytes=size_bytes,
            media_type=media_type,
        )
        asset.validate()
        return asset

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistributionAsset:
        spec = parse_target(str(data["target"]))
        installer_kind = str(data["installer_kind"])
        if installer_kind != spec.installer_kind:
            raise ValueError("Installer kind does not match target")

        return cls.create(
            target=spec.target,
            asset_name=str(data["asset_name"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            media_type=str(data["media_type"]),
        )

    def validate(self) -> None:
        spec = parse_target(self.target)
        if self.installer_kind != spec.installer_kind:
            raise ValueError("Installer kind does not match target")
        if not self.asset_name.strip():
            raise ValueError("Distribution asset name cannot be empty")
        if Path(self.asset_name).name != self.asset_name:
            raise ValueError(
                "Distribution asset name must not contain a path"
            )
        if not self.asset_name.endswith(spec.executable_suffix):
            raise ValueError(
                f"Distribution asset for {self.target} "
                f"must end with {spec.executable_suffix}"
            )
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.sha256.lower()
        ):
            raise ValueError(
                "Distribution asset sha256 must be a "
                "64-character hexadecimal digest"
            )
        if self.size_bytes <= 0:
            raise ValueError(
                "Distribution asset size must be greater than zero"
            )
        if not self.media_type.strip():
            raise ValueError(
                "Distribution asset media_type cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DistributionManifest:
    schema_version: int
    product: str
    version: ReleaseVersion
    release_tag: str
    repository: str
    minimum_python: str
    assets: tuple[DistributionAsset, ...]

    @classmethod
    def create(
        cls,
        *,
        product: str,
        version: ReleaseVersion,
        repository: str,
        minimum_python: str,
        assets: tuple[DistributionAsset, ...],
    ) -> DistributionManifest:
        manifest = cls(
            schema_version=1,
            product=product,
            version=version,
            release_tag=f"v{version}",
            repository=repository,
            minimum_python=minimum_python,
            assets=assets,
        )
        manifest.validate()
        return manifest

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistributionManifest:
        raw_assets = data.get("assets", [])
        if not isinstance(raw_assets, list):
            raise TypeError("Distribution manifest assets must be a list")

        manifest = cls(
            schema_version=int(data["schema_version"]),
            product=str(data["product"]),
            version=ReleaseVersion.parse(str(data["version"])),
            release_tag=str(data["release_tag"]),
            repository=str(data["repository"]),
            minimum_python=str(data["minimum_python"]),
            assets=tuple(
                DistributionAsset.from_dict(item) for item in raw_assets
            ),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported distribution manifest schema_version"
            )
        if not self.product.strip():
            raise ValueError("Distribution product cannot be empty")
        if self.release_tag != f"v{self.version}":
            raise ValueError(
                "Distribution release_tag must match v<version>"
            )

        repository_parts = self.repository.split("/")
        if (
            len(repository_parts) != 2
            or not repository_parts[0]
            or not repository_parts[1]
        ):
            raise ValueError(
                "Distribution repository must use OWNER/REPO format"
            )

        python_parts = self.minimum_python.split(".")
        if (
            len(python_parts) != 2
            or not all(part.isdigit() for part in python_parts)
        ):
            raise ValueError(
                "minimum_python must use MAJOR.MINOR format"
            )

        if not self.assets:
            raise ValueError(
                "Distribution manifest must contain assets"
            )

        targets = [asset.target for asset in self.assets]
        if len(targets) != len(set(targets)):
            raise ValueError("Distribution targets must be unique")

        names = [asset.asset_name for asset in self.assets]
        if len(names) != len(set(names)):
            raise ValueError(
                "Distribution asset names must be unique"
            )

        for asset in self.assets:
            asset.validate()

    def asset_for_target(
        self,
        target: DistributionTarget,
    ) -> DistributionAsset:
        for asset in self.assets:
            if asset.target == target:
                return asset
        raise KeyError(f"No distribution asset for target: {target}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "version": str(self.version),
            "release_tag": self.release_tag,
            "repository": self.repository,
            "minimum_python": self.minimum_python,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    def save(self, destination: str | Path) -> Path:
        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    @classmethod
    def load(cls, source: str | Path) -> DistributionManifest:
        path = Path(source).expanduser().resolve()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(
                "Distribution manifest must contain a JSON object"
            )
        return cls.from_dict(value)
