from __future__ import annotations

from typing import Any

from .plugin_installer import install_plugin
from .plugin_lifecycle import rollback_plugin, upgrade_plugin
from .plugin_management import (
    list_plugins,
    plugin_store_status,
    remove_plugin,
    remove_plugin_version,
)


def install_plugin_command(
    source: str,
    store_root: str,
    empy_version: str,
) -> dict[str, Any]:
    return install_plugin(
        source,
        store_root,
        empy_version=empy_version,
    )


def upgrade_plugin_command(
    source: str,
    store_root: str,
    empy_version: str,
) -> dict[str, Any]:
    return upgrade_plugin(
        source,
        store_root,
        empy_version=empy_version,
    )


def rollback_plugin_command(
    plugin_id: str,
    version: str,
    store_root: str,
) -> dict[str, Any]:
    return rollback_plugin(
        plugin_id,
        version,
        store_root,
    )


def remove_plugin_command(
    plugin_id: str,
    store_root: str,
    *,
    version: str | None = None,
    replacement_version: str | None = None,
) -> dict[str, Any]:
    if version is None:
        return remove_plugin(
            plugin_id,
            store_root,
        )

    return remove_plugin_version(
        plugin_id,
        version,
        store_root,
        replacement_version=replacement_version,
    )


def list_plugins_command(
    store_root: str,
) -> dict[str, Any]:
    return list_plugins(store_root)


def plugin_status_command(
    store_root: str,
) -> dict[str, Any]:
    return plugin_store_status(store_root)
