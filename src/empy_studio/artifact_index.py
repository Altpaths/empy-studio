from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .release_manifest import (
    ReleaseArtifact,
    ReleaseManifest,
)

ARTIFACT_INDEX_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ArtifactIndexEntry:
    name: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str

    @classmethod
    def from_release_artifact(
        cls,
        artifact: ReleaseArtifact,
    ) -> ArtifactIndexEntry:
        return cls(
            name=artifact.name,
            relative_path=artifact.path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            media_type=artifact.media_type,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ArtifactIndexEntry:
        entry = cls(
            name=str(data["name"]),
            relative_path=str(data["relative_path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            media_type=str(data["media_type"]),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Artifact index entry name cannot be empty"
            )
        if Path(self.name).name != self.name:
            raise ValueError(
                "Artifact index entry name must not contain a path"
            )
        if not self.relative_path.strip():
            raise ValueError(
                "Artifact index entry relative_path cannot be empty"
            )

        relative = Path(self.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                "Artifact index entry path must remain relative"
            )

        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.sha256.lower()
        ):
            raise ValueError(
                "Artifact index entry sha256 must be "
                "a 64-character hexadecimal digest"
            )

        if self.size_bytes < 0:
            raise ValueError(
                "Artifact index entry size cannot be negative"
            )

        if not self.media_type.strip():
            raise ValueError(
                "Artifact index entry media_type cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_release_artifact(self) -> ReleaseArtifact:
        artifact = ReleaseArtifact(
            name=self.name,
            path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            media_type=self.media_type,
        )
        artifact.validate()
        return artifact


@dataclass(frozen=True)
class ArtifactIndex:
    schema_version: int
    product: str
    version: str
    tag: str
    artifact_root: str
    entries: tuple[ArtifactIndexEntry, ...]
    total_size_bytes: int
    metadata: dict[str, Any]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ArtifactIndex:
        raw_entries = data.get("entries", [])
        if not isinstance(raw_entries, list):
            raise TypeError(
                "Artifact index entries must be a list"
            )

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError(
                "Artifact index metadata must be a JSON object"
            )

        index = cls(
            schema_version=int(data["schema_version"]),
            product=str(data["product"]),
            version=str(data["version"]),
            tag=str(data["tag"]),
            artifact_root=str(data["artifact_root"]),
            entries=tuple(
                ArtifactIndexEntry.from_dict(item)
                for item in raw_entries
            ),
            total_size_bytes=int(
                data["total_size_bytes"]
            ),
            metadata=metadata,
        )
        index.validate()
        return index

    def validate(self) -> None:
        if self.schema_version != ARTIFACT_INDEX_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported artifact index schema_version"
            )
        if not self.product.strip():
            raise ValueError(
                "Artifact index product cannot be empty"
            )
        if not self.version.strip():
            raise ValueError(
                "Artifact index version cannot be empty"
            )
        if self.tag != f"v{self.version}":
            raise ValueError(
                "Artifact index tag must match v<version>"
            )

        names = [entry.name for entry in self.entries]
        if len(names) != len(set(names)):
            raise ValueError(
                "Artifact index names must be unique"
            )

        paths = [
            entry.relative_path
            for entry in self.entries
        ]
        if len(paths) != len(set(paths)):
            raise ValueError(
                "Artifact index paths must be unique"
            )

        for entry in self.entries:
            entry.validate()

        expected_total = sum(
            entry.size_bytes
            for entry in self.entries
        )
        if self.total_size_bytes != expected_total:
            raise ValueError(
                "Artifact index total_size_bytes is inconsistent"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "version": self.version,
            "tag": self.tag,
            "artifact_root": self.artifact_root,
            "entries": [
                entry.to_dict()
                for entry in self.entries
            ],
            "artifact_count": len(self.entries),
            "total_size_bytes": self.total_size_bytes,
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
    ) -> ArtifactIndex:
        path = Path(source).expanduser().resolve()
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError(
                "Artifact index must contain a JSON object"
            )
        return cls.from_dict(value)

    def apply_to_manifest(
        self,
        manifest: ReleaseManifest,
    ) -> ReleaseManifest:
        if self.product != manifest.product:
            raise ValueError(
                "Artifact index product does not match manifest"
            )
        if self.version != str(manifest.version):
            raise ValueError(
                "Artifact index version does not match manifest"
            )
        if self.tag != manifest.tag:
            raise ValueError(
                "Artifact index tag does not match manifest"
            )

        updated = ReleaseManifest(
            schema_version=manifest.schema_version,
            product=manifest.product,
            version=manifest.version,
            tag=manifest.tag,
            channel=manifest.channel,
            release_name=manifest.release_name,
            notes_file=manifest.notes_file,
            changelog_file=manifest.changelog_file,
            artifacts=tuple(
                entry.to_release_artifact()
                for entry in self.entries
            ),
            previous_version=manifest.previous_version,
            metadata={
                **manifest.metadata,
                "artifact_index": self.to_dict(),
            },
        )
        updated.validate()
        return updated


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(
        path.name,
        strict=False,
    )
    return guessed or "application/octet-stream"


def _normalized_candidates(
    artifact_root: Path,
    candidates: Iterable[str | Path],
) -> list[Path]:
    normalized: list[Path] = []

    for candidate in candidates:
        raw = Path(candidate)
        path = (
            raw
            if raw.is_absolute()
            else artifact_root / raw
        ).expanduser().resolve()

        if artifact_root not in path.parents:
            raise ValueError(
                f"Artifact path escapes artifact_root: {candidate}"
            )

        if not path.is_file():
            raise FileNotFoundError(path)

        normalized.append(path)

    return normalized


def build_artifact_index(
    manifest: ReleaseManifest,
    artifact_root: str | Path,
    candidates: Iterable[str | Path],
    *,
    metadata: dict[str, Any] | None = None,
) -> ArtifactIndex:
    manifest.validate()

    root = Path(
        artifact_root
    ).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    paths = _normalized_candidates(
        root,
        candidates,
    )

    entries = tuple(
        sorted(
            (
                ArtifactIndexEntry(
                    name=path.name,
                    relative_path=path.relative_to(
                        root
                    ).as_posix(),
                    sha256=_sha256(path),
                    size_bytes=path.stat().st_size,
                    media_type=_media_type(path),
                )
                for path in paths
            ),
            key=lambda entry: entry.name,
        )
    )

    index = ArtifactIndex(
        schema_version=ARTIFACT_INDEX_SCHEMA_VERSION,
        product=manifest.product,
        version=str(manifest.version),
        tag=manifest.tag,
        artifact_root=str(root),
        entries=entries,
        total_size_bytes=sum(
            entry.size_bytes
            for entry in entries
        ),
        metadata=metadata or {},
    )
    index.validate()
    return index


def discover_artifacts(
    artifact_root: str | Path,
    *,
    patterns: tuple[str, ...] = ("*",),
    exclude_names: tuple[str, ...] = (
        "artifacts.json",
    ),
) -> tuple[Path, ...]:
    root = Path(
        artifact_root
    ).expanduser().resolve()

    if not root.is_dir():
        raise NotADirectoryError(root)

    discovered: dict[str, Path] = {}

    for pattern in patterns:
        for path in root.glob(pattern):
            if (
                path.is_file()
                and path.name not in exclude_names
            ):
                discovered[
                    path.relative_to(root).as_posix()
                ] = path.resolve()

    return tuple(
        discovered[key]
        for key in sorted(discovered)
    )


def verify_artifact_index(
    index: ArtifactIndex,
) -> tuple[str, ...]:
    root = Path(index.artifact_root)
    issues: list[str] = []

    for entry in index.entries:
        path = (
            root / entry.relative_path
        ).resolve()

        if root not in path.parents:
            issues.append(
                f"Artifact path escapes root: "
                f"{entry.relative_path}"
            )
            continue

        if not path.is_file():
            issues.append(
                f"Artifact is missing: "
                f"{entry.relative_path}"
            )
            continue

        actual_size = path.stat().st_size
        if actual_size != entry.size_bytes:
            issues.append(
                f"Artifact size mismatch: "
                f"{entry.relative_path}"
            )
            continue

        actual_sha256 = _sha256(path)
        if actual_sha256 != entry.sha256:
            issues.append(
                f"Artifact SHA-256 mismatch: "
                f"{entry.relative_path}"
            )

    return tuple(issues)
