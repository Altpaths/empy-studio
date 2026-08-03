from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from .release_version import ReleaseVersion

ReleaseChannel = Literal["stable", "prerelease"]


@dataclass(frozen=True)
class ReleaseArtifact:
    name: str
    path: str
    sha256: str
    size_bytes: int
    media_type: str = "application/octet-stream"

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ReleaseArtifact:
        artifact = cls(
            name=str(data["name"]),
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            media_type=str(
                data.get(
                    "media_type",
                    "application/octet-stream",
                )
            ),
        )
        artifact.validate()
        return artifact

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Release artifact name cannot be empty"
            )
        if Path(self.name).name != self.name:
            raise ValueError(
                "Release artifact name must not contain a path"
            )
        if not self.path.strip():
            raise ValueError(
                "Release artifact path cannot be empty"
            )
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.sha256.lower()
        ):
            raise ValueError(
                "Release artifact sha256 must be a "
                "64-character hexadecimal digest"
            )
        if self.size_bytes < 0:
            raise ValueError(
                "Release artifact size cannot be negative"
            )
        if not self.media_type.strip():
            raise ValueError(
                "Release artifact media_type cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    product: str
    version: ReleaseVersion
    tag: str
    channel: ReleaseChannel
    release_name: str
    notes_file: str
    changelog_file: str
    artifacts: tuple[ReleaseArtifact, ...] = ()
    previous_version: ReleaseVersion | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        product: str,
        version: ReleaseVersion,
        release_name: str,
        notes_file: str,
        changelog_file: str = "CHANGELOG.md",
        artifacts: tuple[ReleaseArtifact, ...] = (),
        previous_version: ReleaseVersion | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReleaseManifest:
        manifest = cls(
            schema_version=1,
            product=product,
            version=version,
            tag=f"v{version}",
            channel=(
                "prerelease"
                if version.is_prerelease
                else "stable"
            ),
            release_name=release_name,
            notes_file=notes_file,
            changelog_file=changelog_file,
            artifacts=artifacts,
            previous_version=previous_version,
            metadata=metadata or {},
        )
        manifest.validate()
        return manifest

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ReleaseManifest:
        raw_artifacts = data.get("artifacts", [])
        if not isinstance(raw_artifacts, list):
            raise TypeError(
                "Release manifest artifacts must be a list"
            )

        previous = data.get("previous_version")
        channel = str(data["channel"])
        if channel not in {"stable", "prerelease"}:
            raise ValueError(
                f"Unsupported release channel: {channel}"
            )

        manifest = cls(
            schema_version=int(data["schema_version"]),
            product=str(data["product"]),
            version=ReleaseVersion.parse(
                str(data["version"])
            ),
            tag=str(data["tag"]),
            channel=cast(
                ReleaseChannel,
                channel,
            ),
            release_name=str(data["release_name"]),
            notes_file=str(data["notes_file"]),
            changelog_file=str(data["changelog_file"]),
            artifacts=tuple(
                ReleaseArtifact.from_dict(item)
                for item in raw_artifacts
            ),
            previous_version=(
                ReleaseVersion.parse(str(previous))
                if previous is not None
                else None
            ),
            metadata=_expect_dict(
                data.get("metadata", {}),
                "metadata",
            ),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported release manifest schema_version"
            )
        if not self.product.strip():
            raise ValueError(
                "Release product cannot be empty"
            )
        if self.tag != f"v{self.version}":
            raise ValueError(
                "Release tag must exactly match v<version>"
            )
        expected_channel: ReleaseChannel = (
            "prerelease"
            if self.version.is_prerelease
            else "stable"
        )
        if self.channel != expected_channel:
            raise ValueError(
                "Release channel does not match version"
            )
        if not self.release_name.strip():
            raise ValueError(
                "Release name cannot be empty"
            )
        if not self.notes_file.strip():
            raise ValueError(
                "Release notes_file cannot be empty"
            )
        if not self.changelog_file.strip():
            raise ValueError(
                "Release changelog_file cannot be empty"
            )
        if (
            self.previous_version is not None
            and self.previous_version >= self.version
        ):
            raise ValueError(
                "previous_version must be lower than version"
            )

        names = [
            artifact.name
            for artifact in self.artifacts
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                "Release artifact names must be unique"
            )

        for artifact in self.artifacts:
            artifact.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "version": str(self.version),
            "tag": self.tag,
            "channel": self.channel,
            "release_name": self.release_name,
            "notes_file": self.notes_file,
            "changelog_file": self.changelog_file,
            "artifacts": [
                artifact.to_dict()
                for artifact in self.artifacts
            ],
            "previous_version": (
                str(self.previous_version)
                if self.previous_version is not None
                else None
            ),
            "metadata": self.metadata,
        }

    def save(self, destination: str | Path) -> Path:
        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

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

    @classmethod
    def load(
        cls,
        source: str | Path,
    ) -> ReleaseManifest:
        path = Path(source).expanduser().resolve()
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError(
                "Release manifest must contain a JSON object"
            )
        return cls.from_dict(value)


def _expect_dict(
    value: Any,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(
            f"{field_name} must contain a JSON object"
        )
    return value
