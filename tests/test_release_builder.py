from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from empy_studio.artifact_index import (
    ArtifactIndex,
)
from empy_studio.release_builder import (
    build_release,
)
from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


def write_changelog(
    root: Path,
) -> Path:
    path = root / "CHANGELOG.md"
    path.write_text(
        """
# Changelog

## [Unreleased]

### Added

- Pending work

## [1.0.0] - 2026-07-20

### Added

- Initial public release
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def manifest() -> ReleaseManifest:
    return ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0"
        ),
        release_name="Empy Studio 1.0.0",
        notes_file="RELEASE_NOTES.md",
    )


def test_builds_complete_release_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text(
        "Empy Studio",
        encoding="utf-8",
    )
    package = source / "src"
    package.mkdir()
    (package / "app.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=(
            "README.md",
            "src",
        ),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    release_dir = Path(
        result.output_dir
    )
    assert release_dir.name == "1.0.0"
    assert Path(result.archive_path).is_file()
    assert Path(
        result.archive_sha256_path
    ).is_file()
    assert Path(
        result.release_notes_path
    ).is_file()
    assert Path(result.manifest_path).is_file()
    assert Path(
        result.artifact_index_path
    ).is_file()


def test_archive_is_deterministic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "stable\n",
        encoding="utf-8",
    )
    changelog = write_changelog(tmp_path)

    first = build_release(
        manifest(),
        source_root=source,
        include_paths=("file.txt",),
        changelog_path=changelog,
        output_dir=tmp_path / "first",
    )
    second = build_release(
        manifest(),
        source_root=source,
        include_paths=("file.txt",),
        changelog_path=changelog,
        output_dir=tmp_path / "second",
    )

    assert Path(first.archive_path).read_bytes() == (
        Path(second.archive_path).read_bytes()
    )


def test_archive_contains_only_selected_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "included.txt").write_text(
        "included",
        encoding="utf-8",
    )
    (source / "excluded.txt").write_text(
        "excluded",
        encoding="utf-8",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=("included.txt",),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    with zipfile.ZipFile(
        result.archive_path,
        "r",
    ) as archive:
        assert archive.namelist() == [
            "included.txt"
        ]


def test_archive_excludes_generated_python_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    package = source / "src" / "package"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    (package / "app.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )
    (cache / "app.cpython-312.pyc").write_bytes(
        b"generated",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=("src",),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    with zipfile.ZipFile(
        result.archive_path,
        "r",
    ) as archive:
        assert archive.namelist() == [
            "src/package/app.py"
        ]


def test_sha256_sidecar_matches_archive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "payload",
        encoding="utf-8",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=("file.txt",),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    expected = hashlib.sha256(
        Path(result.archive_path).read_bytes()
    ).hexdigest()

    sidecar = Path(
        result.archive_sha256_path
    ).read_text(encoding="utf-8")

    assert expected == result.archive_sha256
    assert sidecar.startswith(expected)


def test_release_notes_are_extracted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "payload",
        encoding="utf-8",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=("file.txt",),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    notes = Path(
        result.release_notes_path
    ).read_text(encoding="utf-8")

    assert "## [1.0.0] - 2026-07-20" in notes
    assert "Initial public release" in notes
    assert "Pending work" not in notes


def test_manifest_and_index_are_consistent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "payload",
        encoding="utf-8",
    )

    result = build_release(
        manifest(),
        source_root=source,
        include_paths=("file.txt",),
        changelog_path=write_changelog(
            tmp_path
        ),
        output_dir=tmp_path / "dist",
    )

    manifest_data = json.loads(
        Path(result.manifest_path).read_text(
            encoding="utf-8"
        )
    )
    index = ArtifactIndex.load(
        result.artifact_index_path
    )

    assert (
        manifest_data["version"]
        == index.version
        == "1.0.0"
    )
    assert manifest_data["tag"] == index.tag


def test_rejects_invalid_changelog(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "payload",
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Changelog validation failed",
    ):
        build_release(
            manifest(),
            source_root=source,
            include_paths=("file.txt",),
            changelog_path=changelog,
            output_dir=tmp_path / "dist",
        )


def test_rejects_existing_release_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text(
        "payload",
        encoding="utf-8",
    )
    output = tmp_path / "dist"
    (output / "1.0.0").mkdir(
        parents=True,
    )

    with pytest.raises(FileExistsError):
        build_release(
            manifest(),
            source_root=source,
            include_paths=("file.txt",),
            changelog_path=write_changelog(
                tmp_path
            ),
            output_dir=output,
        )
