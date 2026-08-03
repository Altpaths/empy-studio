from __future__ import annotations

from empy_studio.cli import build_parser


def test_plugin_install_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "install",
            "--source",
            "example.empy-plugin",
            "--store",
            "/plugins",
            "--empy-version",
            "1.0.0",
        ]
    )

    assert args.plugin_command == "install"
    assert args.source == "example.empy-plugin"
    assert args.store == "/plugins"


def test_plugin_upgrade_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "upgrade",
            "--source",
            "example-2.empy-plugin",
            "--store",
            "/plugins",
            "--empy-version",
            "1.0.0",
        ]
    )

    assert args.plugin_command == "upgrade"


def test_plugin_rollback_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "rollback",
            "--plugin-id",
            "example-plugin",
            "--version",
            "1.0.0",
            "--store",
            "/plugins",
        ]
    )

    assert args.plugin_command == "rollback"
    assert args.plugin_id == "example-plugin"
    assert args.version == "1.0.0"


def test_plugin_remove_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "remove",
            "--plugin-id",
            "example-plugin",
            "--version",
            "2.0.0",
            "--replacement-version",
            "1.0.0",
            "--store",
            "/plugins",
        ]
    )

    assert args.plugin_command == "remove"
    assert args.replacement_version == "1.0.0"


def test_plugin_list_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "list",
            "--store",
            "/plugins",
        ]
    )

    assert args.plugin_command == "list"


def test_plugin_status_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "status",
            "--store",
            "/plugins",
        ]
    )

    assert args.plugin_command == "status"
