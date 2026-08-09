from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .artifact_index import build_artifact_index
from .changelog_validator import (
    ChangelogValidationResult,
    validate_release_changelog,
)
from .release_manifest import ReleaseManifest
from .release_version import ReleaseVersion

RELEASE_BUILD_SCHEMA_VERSION = 1
_RELEASE_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
    }
)
_RELEASE_EXCLUDED_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
    }
)


@dataclass(frozen=True)
class ReleaseBuildResult:
    schema_version: int
    product: str
    version: str
    tag: str
    output_dir: str
    archive_path: str
    archive_sha256_path: str
    release_notes_path: str
    manifest_path: str
    artifact_index_path: str
    archive_sha256: str
    archive_size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _write_text_atomic(
    path: Path,
    content: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        content.rstrip() + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _release_notes_from_changelog(
    changelog_path: Path,
    version: ReleaseVersion,
    validation: ChangelogValidationResult,
) -> str:
    release = next(
        (
            item
            for item in validation.releases
            if item.version == version
        ),
        None,
    )
    if release is None:
        raise ValueError(
            f"Version {version} was not found in changelog"
        )

    lines = changelog_path.read_text(
        encoding="utf-8",
    ).splitlines()

    start_index = release.heading_line - 1
    end_index = len(lines)

    for index in range(
        start_index + 1,
        len(lines),
    ):
        if lines[index].startswith("## ["):
            end_index = index
            break

    body = "\n".join(
        lines[start_index:end_index]
    ).strip()

    if not body:
        raise ValueError(
            f"Release notes for version {version} are empty"
        )

    return body + "\n"


def _normalized_source_paths(
    source_root: Path,
    paths: Iterable[str | Path],
) -> tuple[Path, ...]:
    normalized: list[Path] = []

    for raw_path in paths:
        candidate = Path(raw_path)
        path = (
            candidate
            if candidate.is_absolute()
            else source_root / candidate
        ).expanduser().resolve()

        if (
            path != source_root
            and source_root not in path.parents
        ):
            raise ValueError(
                f"Release source escapes source_root: "
                f"{raw_path}"
            )

        if not path.exists():
            raise FileNotFoundError(path)

        normalized.append(path)

    return tuple(normalized)


def _archive_members(
    source_root: Path,
    paths: tuple[Path, ...],
) -> tuple[tuple[Path, str], ...]:
    members: dict[str, Path] = {}

    for path in paths:
        if path.is_file():
            relative = path.relative_to(
                source_root
            ).as_posix()
            members[relative] = path
            continue

        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue

            relative_path = child.relative_to(
                source_root
            )
            if any(
                part in _RELEASE_EXCLUDED_DIRS
                for part in relative_path.parts
            ):
                continue
            if child.suffix.lower() in _RELEASE_EXCLUDED_SUFFIXES:
                continue

            relative = relative_path.as_posix()
            members[relative] = child

    return tuple(
        (members[name], name)
        for name in sorted(members)
    )


def _write_deterministic_zip(
    destination: Path,
    members: tuple[tuple[Path, str], ...],
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, archive_name in members:
            info = zipfile.ZipInfo(
                archive_name,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(
                info,
                source.read_bytes(),
            )


def build_release(
    manifest: ReleaseManifest,
    *,
    source_root: str | Path,
    include_paths: Iterable[str | Path],
    changelog_path: str | Path,
    output_dir: str | Path,
) -> ReleaseBuildResult:
    manifest.validate()

    root = Path(
        source_root
    ).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    changelog = Path(
        changelog_path
    ).expanduser().resolve()

    validation = validate_release_changelog(
        changelog,
        manifest.version,
    )
    if not validation.is_valid:
        raise ValueError(
            "Changelog validation failed: "
            + "; ".join(
                issue.code
                for issue in validation.issues
            )
        )

    output = Path(
        output_dir
    ).expanduser().resolve()
    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    release_dir = output / str(manifest.version)
    if release_dir.exists():
        raise FileExistsError(release_dir)

    staging = Path(
        tempfile.mkdtemp(
            prefix="empy-release-",
            dir=output,
        )
    )

    try:
        normalized_paths = _normalized_source_paths(
            root,
            include_paths,
        )
        members = _archive_members(
            root,
            normalized_paths,
        )
        if not members:
            raise ValueError(
                "Release archive must contain at least one file"
            )

        release_dir_name = (
            f"empy-studio-{manifest.version}"
        )
        archive_path = (
            staging
            / f"{release_dir_name}.zip"
        )
        release_notes_path = (
            staging
            / "RELEASE_NOTES.md"
        )
        manifest_path = (
            staging
            / "release-manifest.json"
        )
        artifact_index_path = (
            staging
            / "artifacts.json"
        )
        archive_sha256_path = (
            staging
            / f"{archive_path.name}.sha256"
        )

        _write_deterministic_zip(
            archive_path,
            members,
        )

        release_notes = (
            _release_notes_from_changelog(
                changelog,
                manifest.version,
                validation,
            )
        )
        _write_text_atomic(
            release_notes_path,
            release_notes,
        )

        archive_sha256 = _sha256(
            archive_path
        )
        _write_text_atomic(
            archive_sha256_path,
            (
                f"{archive_sha256}  "
                f"{archive_path.name}"
            ),
        )

        index = build_artifact_index(
            manifest,
            staging,
            (
                archive_path,
                archive_sha256_path,
                release_notes_path,
            ),
            metadata={
                "builder_schema_version": (
                    RELEASE_BUILD_SCHEMA_VERSION
                ),
            },
        )
        index.save(artifact_index_path)

        final_manifest = index.apply_to_manifest(
            manifest
        )
        _write_json_atomic(
            manifest_path,
            final_manifest.to_dict(),
        )

        final_index = build_artifact_index(
            final_manifest,
            staging,
            (
                archive_path,
                archive_sha256_path,
                release_notes_path,
                artifact_index_path,
                manifest_path,
            ),
            metadata={
                "builder_schema_version": (
                    RELEASE_BUILD_SCHEMA_VERSION
                ),
            },
        )
        final_index.save(
            artifact_index_path
        )

        os.replace(
            staging,
            release_dir,
        )

        return ReleaseBuildResult(
            schema_version=RELEASE_BUILD_SCHEMA_VERSION,
            product=manifest.product,
            version=str(manifest.version),
            tag=manifest.tag,
            output_dir=str(release_dir),
            archive_path=str(
                release_dir / archive_path.name
            ),
            archive_sha256_path=str(
                release_dir
                / archive_sha256_path.name
            ),
            release_notes_path=str(
                release_dir
                / release_notes_path.name
            ),
            manifest_path=str(
                release_dir / manifest_path.name
            ),
            artifact_index_path=str(
                release_dir
                / artifact_index_path.name
            ),
            archive_sha256=archive_sha256,
            archive_size_bytes=(
                release_dir
                / archive_path.name
            ).stat().st_size,
        )

    except Exception:
        shutil.rmtree(
            staging,
            ignore_errors=True,
        )
        raise
