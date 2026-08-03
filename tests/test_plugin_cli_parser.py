from __future__ import annotations

from empy_studio.cli import build_parser


def test_plugin_discover_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "discover",
            "--root",
            "/plugins/one",
            "--root",
            "/plugins/two",
            "--empy-version",
            "1.0.0",
        ]
    )

    assert args.command == "plugin"
    assert args.plugin_command == "discover"
    assert args.root == ["/plugins/one", "/plugins/two"]
    assert args.empy_version == "1.0.0"


def test_plugin_inspect_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "inspect",
            "--package",
            "plugin.empy-plugin",
            "--empy-version",
            "1.0.0",
        ]
    )

    assert args.command == "plugin"
    assert args.plugin_command == "inspect"
    assert args.package == "plugin.empy-plugin"


def test_plugin_validate_parser() -> None:
    args = build_parser().parse_args(
        [
            "plugin",
            "validate",
            "--plugin-root",
            "/plugins/example",
            "--empy-version",
            "1.0.0",
        ]
    )

    assert args.command == "plugin"
    assert args.plugin_command == "validate"
    assert args.plugin_root == "/plugins/example"
