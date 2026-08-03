from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.release_manifest import (
    ReleaseArtifact,
    ReleaseManifest,
)
from empy_studio.release_version import ReleaseVersion


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("0.1.0", "0.1.0"),
        ("1.0.0", "1.0.0"),
        ("1.2.3-alpha.1", "1.2.3-alpha.1"),
        (
            "1.2.3-rc.2+build.17",
            "1.2.3-rc.2+build.17",
        ),
    ],
)
def test_parses_semantic_versions(
    raw: str,
    normalized: str,
) -> None:
    assert str(ReleaseVersion.parse(raw)) == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "1",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.2.3-01",
        "v1.2.3",
        "1.2.3+",
    ],
)
def test_rejects_invalid_versions(raw: str) -> None:
    with pytest.raises(ValueError):
        ReleaseVersion.parse(raw)


def test_semantic_version_precedence() -> None:
    ordered = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]

    parsed = [
        ReleaseVersion.parse(value)
        for value in ordered
    ]

    assert parsed == sorted(parsed)


def test_build_metadata_does_not_change_precedence() -> None:
    left = ReleaseVersion.parse("1.0.0+build.1")
    right = ReleaseVersion.parse("1.0.0+build.2")

    assert not left < right
    assert not right < left


def test_version_bumps_clear_metadata() -> None:
    version = ReleaseVersion.parse(
        "1.2.3-rc.1+build.5"
    )

    assert str(version.bump("major")) == "2.0.0"
    assert str(version.bump("minor")) == "1.3.0"
    assert str(version.bump("patch")) == "1.2.4"


def test_creates_stable_release_manifest() -> None:
    manifest = ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        release_name="Empy Studio 1.0.0",
        notes_file="dist/RELEASE_NOTES.md",
        previous_version=ReleaseVersion.parse(
            "0.9.0"
        ),
    )

    assert manifest.tag == "v1.0.0"
    assert manifest.channel == "stable"


def test_creates_prerelease_manifest() -> None:
    manifest = ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0-rc.1"
        ),
        release_name="Empy Studio 1.0.0 RC1",
        notes_file="dist/RELEASE_NOTES.md",
    )

    assert manifest.channel == "prerelease"


def test_manifest_round_trip(tmp_path: Path) -> None:
    artifact = ReleaseArtifact(
        name="empy-studio-1.0.0.zip",
        path="dist/empy-studio-1.0.0.zip",
        sha256="a" * 64,
        size_bytes=1234,
        media_type="application/zip",
    )
    manifest = ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        release_name="Empy Studio 1.0.0",
        notes_file="dist/RELEASE_NOTES.md",
        artifacts=(artifact,),
        metadata={"commit": "abc123"},
    )

    path = manifest.save(
        tmp_path / "release-manifest.json"
    )
    loaded = ReleaseManifest.load(path)

    assert loaded == manifest


def test_rejects_duplicate_artifact_names() -> None:
    artifact = ReleaseArtifact(
        name="release.zip",
        path="dist/release.zip",
        sha256="a" * 64,
        size_bytes=10,
    )

    with pytest.raises(
        ValueError,
        match="unique",
    ):
        ReleaseManifest.create(
            product="Empy Studio",
            version=ReleaseVersion.parse("1.0.0"),
            release_name="Empy Studio 1.0.0",
            notes_file="RELEASE_NOTES.md",
            artifacts=(artifact, artifact),
        )


def test_rejects_invalid_previous_version() -> None:
    with pytest.raises(
        ValueError,
        match="lower",
    ):
        ReleaseManifest.create(
            product="Empy Studio",
            version=ReleaseVersion.parse("1.0.0"),
            release_name="Empy Studio 1.0.0",
            notes_file="RELEASE_NOTES.md",
            previous_version=ReleaseVersion.parse(
                "1.0.0"
            ),
        )


def test_rejects_tag_mismatch() -> None:
    manifest = ReleaseManifest(
        schema_version=1,
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        tag="release-1.0.0",
        channel="stable",
        release_name="Empy Studio 1.0.0",
        notes_file="RELEASE_NOTES.md",
        changelog_file="CHANGELOG.md",
    )

    with pytest.raises(
        ValueError,
        match="tag",
    ):
        manifest.validate()
