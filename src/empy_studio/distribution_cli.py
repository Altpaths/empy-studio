from __future__ import annotations

import argparse
from typing import Any

from .distribution_builder import (
    DistributionBuildConfig,
    build_distribution,
)
from .distribution_manifest import (
    DistributionManifest,
)
from .distribution_sync import (
    UrllibDistributionTransport,
    sync_distribution_links,
)
from .environment_preflight import (
    run_environment_preflight,
)


def register_distribution_parser(
    subparsers: Any,
) -> None:
    parser = subparsers.add_parser(
        "distribution",
        help=(
            "Build and synchronize installers "
            "for supported platforms"
        ),
    )
    commands = parser.add_subparsers(
        dest="distribution_command",
        required=True,
    )

    build = commands.add_parser("build")
    build.add_argument(
        "--config",
        required=True,
    )
    build.add_argument("--output")

    preflight = commands.add_parser(
        "preflight"
    )
    preflight.add_argument(
        "--minimum-python",
        required=True,
    )
    preflight.add_argument(
        "--install-root"
    )
    preflight.add_argument("--output")

    sync = commands.add_parser("sync")
    sync.add_argument(
        "--manifest",
        required=True,
    )
    sync.add_argument(
        "--selection",
        choices=(
            "latest-stable",
            "latest-prerelease",
            "tag",
        ),
        default="latest-stable",
    )
    sync.add_argument("--tag")
    sync.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
    )
    sync.add_argument(
        "--links-output",
        required=True,
    )
    sync.add_argument("--output")

    inspect = commands.add_parser("inspect")
    inspect.add_argument(
        "--manifest",
        required=True,
    )
    inspect.add_argument("--output")


def run_distribution_command(
    args: argparse.Namespace,
) -> dict[str, Any]:
    command = args.distribution_command

    if command == "build":
        config = (
            DistributionBuildConfig.load(
                args.config
            )
        )
        return build_distribution(
            config
        ).to_dict()

    if command == "preflight":
        return run_environment_preflight(
            minimum_python=(
                args.minimum_python
            ),
            install_root=args.install_root,
        ).to_dict()

    if command == "sync":
        manifest = (
            DistributionManifest.load(
                args.manifest
            )
        )

        import os

        token = os.environ.get(
            args.token_env
        )
        link_map = sync_distribution_links(
            manifest,
            selection=args.selection,
            tag=args.tag,
            token=token,
            transport=(
                UrllibDistributionTransport()
            ),
        )
        link_map.save(
            args.links_output
        )
        return link_map.to_dict()

    if command == "inspect":
        manifest = (
            DistributionManifest.load(
                args.manifest
            )
        )
        return {
            "status": "valid",
            "manifest": manifest.to_dict(),
        }

    raise ValueError(
        f"Unsupported distribution command: "
        f"{command}"
    )
