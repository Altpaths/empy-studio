from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.plugin_store import (
    InstalledVersion,
    PluginInventoryEntry,
    PluginStore,
    TransactionRecord,
    utc_now,
)


def test_initializes_standard_store_layout(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")

    inventory = store.initialize()

    assert inventory.revision == 0
    assert store.inventory_path.is_file()
    assert store.transactions_path.is_dir()
    assert store.packages_path.is_dir()
    assert store.active_path.is_dir()


def test_inventory_round_trip_and_atomic_revision(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")
    inventory = store.initialize()

    inventory.plugins["example-plugin"] = PluginInventoryEntry(
        plugin_id="example-plugin",
        active_version="1.0.0",
        versions={
            "1.0.0": InstalledVersion(
                version="1.0.0",
                package_sha256="a" * 64,
                installed_at=utc_now(),
                source="file:///example.empy-plugin",
                path="packages/example-plugin/1.0.0",
            )
        },
    )
    inventory.revision += 1

    store.save_inventory(inventory)
    loaded = store.load_inventory()

    assert loaded.revision == 1
    assert (
        loaded.plugins["example-plugin"].active_version
        == "1.0.0"
    )
    assert (
        loaded.plugins["example-plugin"]
        .versions["1.0.0"]
        .package_sha256
        == "a" * 64
    )


def test_rejects_active_version_not_installed(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")
    inventory = store.initialize()
    inventory.plugins["broken"] = PluginInventoryEntry(
        plugin_id="broken",
        active_version="2.0.0",
        versions={},
    )

    with pytest.raises(
        ValueError,
        match="Active version",
    ):
        store.save_inventory(inventory)


def test_store_lock_prevents_concurrent_mutation(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")
    store.initialize()

    with store.lock():
        assert store.lock_path.is_file()

        with pytest.raises(
            RuntimeError,
            match="locked",
        ), store.lock():
            pass

    assert not store.lock_path.exists()


def test_transaction_journal_round_trip(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")
    store.initialize()
    timestamp = utc_now()

    record = TransactionRecord(
        transaction_id="tx-001",
        operation="install",
        plugin_id="example-plugin",
        version="1.0.0",
        status="staged",
        created_at=timestamp,
        updated_at=timestamp,
        details={"source": "local"},
    )

    path = store.write_transaction(record)
    loaded = store.read_transaction("tx-001")

    assert path.is_file()
    assert loaded == record


def test_rejects_invalid_inventory_format(
    tmp_path: Path,
) -> None:
    store = PluginStore(tmp_path / "store")
    store.root.mkdir(parents=True)
    store.inventory_path.write_text(
        json.dumps(
            {
                "format": "unknown-format",
                "revision": 0,
                "plugins": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        store.load_inventory()
