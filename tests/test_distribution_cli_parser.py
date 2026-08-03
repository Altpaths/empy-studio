from __future__ import annotations

from empy_studio.cli import build_parser


def test_distribution_build_parser() -> None:
    args = build_parser().parse_args(
        [
            "distribution",
            "build",
            "--config",
            "distribution-build.json",
        ]
    )

    assert (
        args.distribution_command
        == "build"
    )


def test_distribution_preflight_parser() -> None:
    args = build_parser().parse_args(
        [
            "distribution",
            "preflight",
            "--minimum-python",
            "3.10",
        ]
    )

    assert (
        args.distribution_command
        == "preflight"
    )


def test_distribution_sync_parser() -> None:
    args = build_parser().parse_args(
        [
            "distribution",
            "sync",
            "--manifest",
            "distribution-manifest.json",
            "--links-output",
            "distribution-links.json",
        ]
    )

    assert (
        args.distribution_command
        == "sync"
    )


def test_distribution_inspect_parser() -> None:
    args = build_parser().parse_args(
        [
            "distribution",
            "inspect",
            "--manifest",
            "distribution-manifest.json",
        ]
    )

    assert (
        args.distribution_command
        == "inspect"
    )
