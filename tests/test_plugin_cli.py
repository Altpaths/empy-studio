from __future__ import annotations

import json
from pathlib import Path

from empy_studio.plugin_cli import (
    discover_plugins,
    inspect_plugin_package,
    validate_installed_plugin,
)
from empy_studio.plugin_package import build_package


def create_plugin(root: Path) -> Path:
    plugin_root = root / "example-plugin"
    payload = plugin_root / "payload"
    payload.mkdir(parents=True)

    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "example-plugin",
                "name": "Example Plugin",
                "version": "1.0.0",
                "empy_requires": ">=0.1.0",
                "entrypoint": "example_plugin:Plugin",
                "hooks": ["agent"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (payload / "example_plugin.py").write_text(
        "class Plugin:\n    pass\n",
        encoding="utf-8",
    )
    return plugin_root


def test_discover_plugins_returns_metadata(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    create_plugin(store)

    result = discover_plugins(
        [str(store)],
        "1.0.0",
    )

    assert result["status"] == "ok"
    assert result["plugin_count"] == 1
    assert (
        result["plugins"][0]["manifest"]["plugin_id"]
        == "example-plugin"
    )


def test_inspect_plugin_package_returns_verified_manifest(
    tmp_path: Path,
) -> None:
    source = create_plugin(tmp_path)
    package = build_package(
        source,
        tmp_path / "example-plugin.empy-plugin",
    )

    result = inspect_plugin_package(
        str(package),
        "1.0.0",
    )

    assert result["manifest"]["plugin_id"] == "example-plugin"
    assert result["records"]


def test_validate_installed_plugin(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    plugin = create_plugin(store)

    result = validate_installed_plugin(
        str(plugin),
        "1.0.0",
    )

    assert result["status"] == "valid"
    assert (
        result["plugin"]["manifest"]["plugin_id"]
        == "example-plugin"
    )


def test_validate_missing_plugin_directory(
    tmp_path: Path,
) -> None:
    result = validate_installed_plugin(
        str(tmp_path / "missing"),
        "1.0.0",
    )

    assert result["status"] == "invalid"
    assert (
        result["issues"][0]["error_type"]
        == "missing_plugin_root"
    )
