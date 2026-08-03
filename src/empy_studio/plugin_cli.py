from __future__ import annotations

from pathlib import Path
from typing import Any

from .plugin_discovery import discover_installed_plugins
from .plugin_package import inspect_package


def discover_plugins(
    roots: list[str],
    empy_version: str,
) -> dict[str, Any]:
    return discover_installed_plugins(
        [Path(root) for root in roots],
        empy_version=empy_version,
    )


def inspect_plugin_package(
    package_path: str,
    empy_version: str,
) -> dict[str, Any]:
    return inspect_package(
        package_path,
        empy_version=empy_version,
    ).to_dict()


def validate_installed_plugin(
    plugin_root: str,
    empy_version: str,
) -> dict[str, Any]:
    root = Path(plugin_root).expanduser().resolve()

    if not root.is_dir():
        return {
            "status": "invalid",
            "plugin_root": str(root),
            "issues": [
                {
                    "path": str(root),
                    "error_type": "missing_plugin_root",
                    "message": "Installed plugin directory does not exist",
                }
            ],
        }

    discovery = discover_installed_plugins(
        [root.parent],
        empy_version=empy_version,
    )

    matches = [
        item
        for item in discovery["plugins"]
        if item["root"] == str(root)
    ]

    if not matches:
        relevant_issues = [
            issue
            for issue in discovery["issues"]
            if issue["path"].startswith(str(root))
        ]
        return {
            "status": "invalid",
            "plugin_root": str(root),
            "issues": relevant_issues or discovery["issues"],
        }

    return {
        "status": "valid",
        "plugin_root": str(root),
        "plugin": matches[0],
    }
