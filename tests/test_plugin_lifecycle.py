from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.plugin_lifecycle import (
    rollback_plugin,
    upgrade_plugin,
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


def test_upgrade_retains_previous_version(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    version_one = create_package(
        tmp_path,
        version="1.0.0",
    )
    version_two = create_package(
        tmp_path,
        version="2.0.0",
    )

    upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )
    result = upgrade_plugin(
        str(version_two),
        store_root,
        empy_version="1.0.0",
    )

    store = PluginStore(store_root)
    inventory = store.load_inventory()
    entry = inventory.plugins["example-plugin"]

    assert result["previous_active_version"] == "1.0.0"
    assert entry.active_version == "2.0.0"
    assert sorted(entry.versions) == ["1.0.0", "2.0.0"]
    assert (
        result["retained_previous_versions"]
        == ["1.0.0"]
    )


def test_rollback_changes_active_version_only(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    version_one = create_package(
        tmp_path,
        version="1.0.0",
    )
    version_two = create_package(
        tmp_path,
        version="2.0.0",
    )

    upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )
    upgrade_plugin(
        str(version_two),
        store_root,
        empy_version="1.0.0",
    )

    result = rollback_plugin(
        "example-plugin",
        "1.0.0",
        store_root,
    )

    store = PluginStore(store_root)
    inventory = store.load_inventory()
    entry = inventory.plugins["example-plugin"]

    assert result["status"] == "rolled_back"
    assert result["previous_active_version"] == "2.0.0"
    assert result["active_version"] == "1.0.0"
    assert entry.active_version == "1.0.0"
    assert sorted(entry.versions) == ["1.0.0", "2.0.0"]

    pointer = json.loads(
        (
            store.active_path / "example-plugin.json"
        ).read_text(encoding="utf-8")
    )
    assert pointer["version"] == "1.0.0"


def test_rollback_records_committed_transaction(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    version_one = create_package(
        tmp_path,
        version="1.0.0",
    )

    upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )

    result = rollback_plugin(
        "example-plugin",
        "1.0.0",
        store_root,
    )

    transaction = PluginStore(
        store_root
    ).read_transaction(result["transaction_id"])

    assert transaction.operation == "rollback"
    assert transaction.status == "committed"
    assert (
        transaction.details["active_version"]
        == "1.0.0"
    )


def test_rejects_rollback_to_missing_version(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    version_one = create_package(
        tmp_path,
        version="1.0.0",
    )

    upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )

    with pytest.raises(
        ValueError,
        match="is not installed",
    ):
        rollback_plugin(
            "example-plugin",
            "9.9.9",
            store_root,
        )

    inventory = PluginStore(store_root).load_inventory()
    assert (
        inventory.plugins["example-plugin"].active_version
        == "1.0.0"
    )


def test_rejects_rollback_for_unknown_plugin(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"

    with pytest.raises(
        KeyError,
        match="not installed",
    ):
        rollback_plugin(
            "missing-plugin",
            "1.0.0",
            store_root,
        )


def test_failed_pointer_update_restores_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_root = tmp_path / "store"
    version_one = create_package(
        tmp_path,
        version="1.0.0",
    )
    version_two = create_package(
        tmp_path,
        version="2.0.0",
    )

    upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )
    upgrade_plugin(
        str(version_two),
        store_root,
        empy_version="1.0.0",
    )

    original_replace = __import__("os").replace

    def fail_pointer_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        destination_path = Path(destination)
        if destination_path.name == "example-plugin.json":
            raise OSError("pointer update failed")
        original_replace(source, destination)

    monkeypatch.setattr(
        "empy_studio.plugin_lifecycle.os.replace",
        fail_pointer_replace,
    )

    with pytest.raises(
        OSError,
        match="pointer update failed",
    ):
        rollback_plugin(
            "example-plugin",
            "1.0.0",
            store_root,
        )

    store = PluginStore(store_root)
    inventory = store.load_inventory()
    assert (
        inventory.plugins["example-plugin"].active_version
        == "2.0.0"
    )

    pointer = json.loads(
        (
            store.active_path / "example-plugin.json"
        ).read_text(encoding="utf-8")
    )
    assert pointer["version"] == "2.0.0"
