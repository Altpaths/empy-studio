from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.plugin_lifecycle import upgrade_plugin
from empy_studio.plugin_management import (
    list_plugins,
    plugin_store_status,
    remove_plugin,
    remove_plugin_version,
)
from empy_studio.plugin_package import build_package
from empy_studio.plugin_store import PluginStore


def create_package(
    tmp_path: Path,
    *,
    version: str,
) -> Path:
    source = tmp_path / f"source-{version}"
    payload = source / "payload"
    payload.mkdir(parents=True)

    (source / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "example-plugin",
                "name": "Example Plugin",
                "version": version,
                "empy_requires": ">=0.1.0",
                "entrypoint": "plugin_main:Plugin",
                "hooks": ["agent"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (payload / "plugin_main.py").write_text(
        (
            "class Plugin:\n"
            f"    version = {version!r}\n"
        ),
        encoding="utf-8",
    )

    return build_package(
        source,
        tmp_path / f"example-plugin-{version}.empy-plugin",
    )


def install_two_versions(
    tmp_path: Path,
) -> Path:
    store_root = tmp_path / "store"

    upgrade_plugin(
        str(create_package(tmp_path, version="1.0.0")),
        store_root,
        empy_version="1.0.0",
    )
    upgrade_plugin(
        str(create_package(tmp_path, version="2.0.0")),
        store_root,
        empy_version="1.0.0",
    )

    return store_root


def test_lists_installed_plugins_and_versions(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = list_plugins(store_root)

    assert result["status"] == "ok"
    assert result["plugin_count"] == 1
    assert (
        result["plugins"][0]["active_version"]
        == "2.0.0"
    )
    assert result["plugins"][0]["version_count"] == 2
    assert all(
        version["path_exists"]
        for version in result["plugins"][0]["versions"]
    )


def test_reports_healthy_store(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = plugin_store_status(store_root)

    assert result["status"] == "healthy"
    assert result["issue_count"] == 0


def test_reports_missing_installed_path(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)
    store = PluginStore(store_root)
    inventory = store.load_inventory()
    record = (
        inventory.plugins["example-plugin"]
        .versions["1.0.0"]
    )

    import shutil

    shutil.rmtree(store.root / record.path)

    result = plugin_store_status(store_root)

    assert result["status"] == "degraded"
    assert any(
        issue["error_type"] == "missing_installed_path"
        for issue in result["issues"]
    )


def test_rejects_removing_active_version_without_replacement(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    with pytest.raises(
        ValueError,
        match="replacement_version",
    ):
        remove_plugin_version(
            "example-plugin",
            "2.0.0",
            store_root,
        )


def test_removes_inactive_version(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = remove_plugin_version(
        "example-plugin",
        "1.0.0",
        store_root,
    )

    inventory = PluginStore(store_root).load_inventory()
    entry = inventory.plugins["example-plugin"]

    assert result["status"] == "removed"
    assert sorted(entry.versions) == ["2.0.0"]
    assert entry.active_version == "2.0.0"


def test_removes_active_version_with_replacement(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = remove_plugin_version(
        "example-plugin",
        "2.0.0",
        store_root,
        replacement_version="1.0.0",
    )

    store = PluginStore(store_root)
    inventory = store.load_inventory()
    entry = inventory.plugins["example-plugin"]

    assert result["active_version"] == "1.0.0"
    assert entry.active_version == "1.0.0"
    assert sorted(entry.versions) == ["1.0.0"]

    pointer = json.loads(
        (
            store.active_path / "example-plugin.json"
        ).read_text(encoding="utf-8")
    )
    assert pointer["version"] == "1.0.0"


def test_removes_complete_plugin(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = remove_plugin(
        "example-plugin",
        store_root,
    )

    store = PluginStore(store_root)
    inventory = store.load_inventory()

    assert result["removed_versions"] == [
        "1.0.0",
        "2.0.0",
    ]
    assert "example-plugin" not in inventory.plugins
    assert not (
        store.active_path / "example-plugin.json"
    ).exists()


def test_records_remove_transaction(
    tmp_path: Path,
) -> None:
    store_root = install_two_versions(tmp_path)

    result = remove_plugin_version(
        "example-plugin",
        "1.0.0",
        store_root,
    )

    transaction = PluginStore(
        store_root
    ).read_transaction(result["transaction_id"])

    assert transaction.operation == "remove"
    assert transaction.status == "committed"
    assert (
        transaction.details["removed_version"]
        == "1.0.0"
    )
