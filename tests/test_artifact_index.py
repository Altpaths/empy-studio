from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from empy_studio.artifact_index import (
    ArtifactIndex,
    build_artifact_index,
    discover_artifacts,
    verify_artifact_index,
)
from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_version import ReleaseVersion


def manifest() -> ReleaseManifest:
    return ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        release_name="Empy Studio 1.0.0",
        notes_file="dist/RELEASE_NOTES.md",
    )


def test_builds_deterministic_artifact_index(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    zip_file = dist / "empy-studio-1.0.0.zip"
    zip_file.write_bytes(b"zip-content")

    manifest_file = dist / "release-manifest.json"
    manifest_file.write_text(
        "{}\n",
        encoding="utf-8",
    )

    index = build_artifact_index(
        manifest(),
        dist,
        [
            manifest_file.name,
            zip_file.name,
        ],
        metadata={"commit": "abc123"},
    )

    assert [
        entry.name
        for entry in index.entries
    ] == [
        "empy-studio-1.0.0.zip",
        "release-manifest.json",
    ]
    assert index.total_size_bytes == (
        zip_file.stat().st_size
        + manifest_file.stat().st_size
    )
    assert index.metadata["commit"] == "abc123"


def test_calculates_sha256_and_media_type(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    artifact = dist / "release.zip"
    artifact.write_bytes(b"release-data")

    index = build_artifact_index(
        manifest(),
        dist,
        [artifact],
    )
    entry = index.entries[0]

    assert entry.sha256 == hashlib.sha256(
        b"release-data"
    ).hexdigest()
    assert entry.media_type == "application/zip"


def test_index_round_trip(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "release.zip").write_bytes(b"data")

    index = build_artifact_index(
        manifest(),
        dist,
        ["release.zip"],
    )
    path = index.save(dist / "artifacts.json")

    loaded = ArtifactIndex.load(path)

    assert loaded == index


def test_applies_entries_to_release_manifest(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "release.zip").write_bytes(b"data")

    original = manifest()
    index = build_artifact_index(
        original,
        dist,
        ["release.zip"],
    )

    updated = index.apply_to_manifest(original)

    assert len(updated.artifacts) == 1
    assert updated.artifacts[0].name == "release.zip"
    assert (
        updated.metadata["artifact_index"]
        ["artifact_count"]
        == 1
    )


def test_rejects_artifact_outside_root(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"outside")

    with pytest.raises(
        ValueError,
        match="escapes",
    ):
        build_artifact_index(
            manifest(),
            dist,
            [outside],
        )


def test_rejects_duplicate_public_names(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    first = dist / "one"
    second = dist / "two"
    first.mkdir(parents=True)
    second.mkdir()

    (first / "release.zip").write_bytes(b"one")
    (second / "release.zip").write_bytes(b"two")

    with pytest.raises(
        ValueError,
        match="names must be unique",
    ):
        build_artifact_index(
            manifest(),
            dist,
            [
                "one/release.zip",
                "two/release.zip",
            ],
        )


def test_discovers_artifacts_by_patterns(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    (dist / "release.zip").write_bytes(b"zip")
    (dist / "release.sha256").write_text(
        "hash",
        encoding="utf-8",
    )
    (dist / "artifacts.json").write_text(
        "{}",
        encoding="utf-8",
    )

    discovered = discover_artifacts(
        dist,
        patterns=("*.zip", "*.sha256", "*.json"),
    )

    assert [
        path.name
        for path in discovered
    ] == [
        "release.sha256",
        "release.zip",
    ]


def test_verifies_unchanged_artifacts(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / "release.zip"
    artifact.write_bytes(b"stable")

    index = build_artifact_index(
        manifest(),
        dist,
        [artifact],
    )

    assert verify_artifact_index(index) == ()


def test_detects_tampered_artifact(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / "release.zip"
    artifact.write_bytes(b"stable")

    index = build_artifact_index(
        manifest(),
        dist,
        [artifact],
    )
    artifact.write_bytes(b"tampered")

    issues = verify_artifact_index(index)

    assert any(
        "mismatch" in issue
        for issue in issues
    )
