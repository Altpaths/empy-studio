from __future__ import annotations

from empy_studio.cli import build_parser


def test_release_validate_parser() -> None:
    args = build_parser().parse_args(
        [
            "release",
            "validate",
            "--manifest",
            "release-manifest.json",
            "--changelog",
            "CHANGELOG.md",
        ]
    )
    assert args.release_command == "validate"


def test_release_build_parser() -> None:
    args = build_parser().parse_args(
        [
            "release",
            "build",
            "--manifest",
            "release-manifest.json",
            "--source-root",
            ".",
            "--include",
            "src",
            "--changelog",
            "CHANGELOG.md",
            "--output-dir",
            "dist",
        ]
    )
    assert args.include == ["src"]


def test_release_tag_parser() -> None:
    args = build_parser().parse_args(
        [
            "release",
            "tag",
            "--manifest",
            "release-manifest.json",
            "--repository-root",
            ".",
            "--push",
        ]
    )
    assert args.push is True


def test_release_publish_parser() -> None:
    args = build_parser().parse_args(
        [
            "release",
            "publish",
            "--manifest",
            "release-manifest.json",
            "--artifact-index",
            "artifacts.json",
            "--release-notes",
            "RELEASE_NOTES.md",
            "--repository-root",
            ".",
            "--repository",
            "Altpaths/empy-studio",
            "--rollback-dir",
            "dist/records",
        ]
    )
    assert args.release_command == "publish"


def test_release_inspect_parser() -> None:
    args = build_parser().parse_args(
        [
            "release",
            "inspect",
            "--manifest",
            "release-manifest.json",
            "--artifact-index",
            "artifacts.json",
        ]
    )
    assert args.release_command == "inspect"
