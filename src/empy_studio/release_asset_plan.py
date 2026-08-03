from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .release_version import ReleaseVersion


@dataclass(frozen=True)
class PlannedReleaseAsset:
    name: str
    path: str
    media_type: str
    required: bool
    sha256: str | None = None
    size_bytes: int | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Release asset name cannot be empty"
            )
        if Path(self.name).name != self.name:
            raise ValueError(
                "Release asset name must not contain a path"
            )
        if not self.path.strip():
            raise ValueError(
                "Release asset path cannot be empty"
            )
        if not self.media_type.strip():
            raise ValueError(
                "Release asset media type cannot be empty"
            )
        if (
            self.sha256 is not None
            and (
                len(self.sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in self.sha256.lower()
                )
            )
        ):
            raise ValueError(
                "Release asset SHA-256 must be valid"
            )
        if (
            self.size_bytes is not None
            and self.size_bytes < 0
        ):
            raise ValueError(
                "Release asset size cannot be negative"
            )

    @property
    def materialized(self) -> bool:
        return (
            self.sha256 is not None
            and self.size_bytes is not None
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["materialized"] = self.materialized
        return value


@dataclass(frozen=True)
class ReleaseAssetPlan:
    schema_version: int
    product: str
    candidate_version: ReleaseVersion
    target_version: ReleaseVersion
    candidate_tag: str
    stable_tag: str
    release_notes_path: str
    assets: tuple[PlannedReleaseAsset, ...]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported release asset-plan schema"
            )
        if not self.product.strip():
            raise ValueError(
                "Release asset-plan product cannot be empty"
            )
        if self.candidate_tag != (
            f"v{self.candidate_version}"
        ):
            raise ValueError(
                "candidate_tag must match candidate_version"
            )
        if self.stable_tag != (
            f"v{self.target_version}"
        ):
            raise ValueError(
                "stable_tag must match target_version"
            )
        if not self.assets:
            raise ValueError(
                "Release asset plan cannot be empty"
            )

        names = [
            asset.name
            for asset in self.assets
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                "Release asset names must be unique"
            )

        for asset in self.assets:
            asset.validate()

    @property
    def ready(self) -> bool:
        return all(
            (
                asset.materialized
                if asset.required
                else True
            )
            for asset in self.assets
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "candidate_version": str(
                self.candidate_version
            ),
            "target_version": str(
                self.target_version
            ),
            "candidate_tag": self.candidate_tag,
            "stable_tag": self.stable_tag,
            "release_notes_path": (
                self.release_notes_path
            ),
            "ready": self.ready,
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ],
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )
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


def materialize_asset_plan(
    plan: ReleaseAssetPlan,
    *,
    project_root: str | Path,
) -> ReleaseAssetPlan:
    plan.validate()

    root = Path(
        project_root
    ).expanduser().resolve()
    materialized: list[
        PlannedReleaseAsset
    ] = []

    for asset in plan.assets:
        path = (
            root / asset.path
        ).resolve()

        if (
            root not in path.parents
            and path != root
        ):
            raise ValueError(
                "Release asset path escapes project root"
            )

        if not path.is_file():
            materialized.append(asset)
            continue

        digest = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        materialized.append(
            PlannedReleaseAsset(
                name=asset.name,
                path=asset.path,
                media_type=asset.media_type,
                required=asset.required,
                sha256=digest,
                size_bytes=path.stat().st_size,
            )
        )

    result = ReleaseAssetPlan(
        schema_version=plan.schema_version,
        product=plan.product,
        candidate_version=(
            plan.candidate_version
        ),
        target_version=plan.target_version,
        candidate_tag=plan.candidate_tag,
        stable_tag=plan.stable_tag,
        release_notes_path=(
            plan.release_notes_path
        ),
        assets=tuple(materialized),
    )
    result.validate()
    return result


def default_release_asset_plan(
) -> ReleaseAssetPlan:
    candidate = ReleaseVersion.parse(
        "1.0.0-rc.1"
    )
    target = ReleaseVersion.parse(
        "1.0.0"
    )

    return ReleaseAssetPlan(
        schema_version=1,
        product="Empy Studio",
        candidate_version=candidate,
        target_version=target,
        candidate_tag=f"v{candidate}",
        stable_tag=f"v{target}",
        release_notes_path=(
            "examples/release/"
            "release-notes-v1.0.0-rc.1.md"
        ),
        assets=(
            PlannedReleaseAsset(
                name=(
                    "empy_studio-1.0.0rc1-"
                    "py3-none-any.whl"
                ),
                path=(
                    "dist/"
                    "empy_studio-1.0.0rc1-"
                    "py3-none-any.whl"
                ),
                media_type=(
                    "application/zip"
                ),
                required=True,
            ),
            PlannedReleaseAsset(
                name=(
                    "empy_studio-1.0.0rc1.tar.gz"
                ),
                path=(
                    "dist/"
                    "empy_studio-1.0.0rc1.tar.gz"
                ),
                media_type=(
                    "application/gzip"
                ),
                required=True,
            ),
            PlannedReleaseAsset(
                name=(
                    "distribution-manifest.json"
                ),
                path=(
                    "dist/distribution/1.0.0-rc.1/"
                    "distribution-manifest.json"
                ),
                media_type=(
                    "application/json"
                ),
                required=True,
            ),
            PlannedReleaseAsset(
                name="artifact-index.json",
                path=(
                    "dist/release/"
                    "artifact-index.json"
                ),
                media_type=(
                    "application/json"
                ),
                required=True,
            ),
            PlannedReleaseAsset(
                name="release-candidate.json",
                path=(
                    "dist/release/"
                    "release-candidate.json"
                ),
                media_type=(
                    "application/json"
                ),
                required=True,
            ),
        ),
    )
