from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .plugin_installer import install_plugin
from .plugin_store import (
    PluginInventory,
    PluginStore,
    TransactionRecord,
    utc_now,
)


def _copy_inventory(inventory: PluginInventory) -> PluginInventory:
    return PluginInventory.from_dict(inventory.to_dict())


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _update_transaction(
    store: PluginStore,
    record: TransactionRecord,
    *,
    status: str,
    details: dict[str, Any] | None = None,
) -> TransactionRecord:
    updated = replace(
        record,
        status=status,
        updated_at=utc_now(),
        details={
            **record.details,
            **(details or {}),
        },
    )
    store.write_transaction(updated)
    return updated


def upgrade_plugin(
    source: str,
    store_root: str | Path,
    *,
    empy_version: str,
    timeout_seconds: float = 30.0,
    max_bytes: int = 100 * 1024 * 1024,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()

    before = store.load_inventory()
    plugin_ids_before = set(before.plugins)

    result = install_plugin(
        source,
        store_root,
        empy_version=empy_version,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )

    plugin_id = str(result["plugin_id"])
    version = str(result["version"])

    after = store.load_inventory()
    entry = after.plugins[plugin_id]

    previous_versions = [
        installed_version
        for installed_version in entry.versions
        if installed_version != version
    ]

    previous_active = None
    if plugin_id in plugin_ids_before:
        previous_active = before.plugins[plugin_id].active_version

    return {
        **result,
        "operation": "upgrade",
        "previous_active_version": previous_active,
        "installed_versions": sorted(entry.versions),
        "retained_previous_versions": sorted(previous_versions),
    }


def rollback_plugin(
    plugin_id: str,
    target_version: str,
    store_root: str | Path,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()

    transaction_id = f"rollback-{uuid.uuid4().hex}"
    timestamp = utc_now()
    transaction = TransactionRecord(
        transaction_id=transaction_id,
        operation="rollback",
        plugin_id=plugin_id,
        version=target_version,
        status="created",
        created_at=timestamp,
        updated_at=timestamp,
        details={},
    )
    store.write_transaction(transaction)

    original_inventory: PluginInventory | None = None
    pointer_path = store.active_path / f"{plugin_id}.json"
    previous_pointer: str | None = None

    try:
        with store.lock():
            inventory = store.load_inventory()
            original_inventory = _copy_inventory(inventory)

            entry = inventory.plugins.get(plugin_id)
            if entry is None:
                raise KeyError(
                    f"Plugin is not installed: {plugin_id}"
                )

            if target_version not in entry.versions:
                raise ValueError(
                    f"Plugin {plugin_id} version {target_version} "
                    f"is not installed"
                )

            previous_active = entry.active_version

            if pointer_path.is_file():
                previous_pointer = pointer_path.read_text(
                    encoding="utf-8"
                )

            transaction = _update_transaction(
                store,
                transaction,
                status="validated",
                details={
                    "previous_active_version": previous_active,
                    "target_version": target_version,
                },
            )

            record = entry.versions[target_version]
            installed_path = store.root / record.path

            if not installed_path.is_dir():
                raise FileNotFoundError(
                    f"Installed plugin path is missing: {installed_path}"
                )

            entry.active_version = target_version
            inventory.revision += 1

            store.save_inventory(inventory)

            _write_json_atomic(
                pointer_path,
                {
                    "plugin_id": plugin_id,
                    "version": target_version,
                    "path": record.path,
                    "updated_at": utc_now(),
                },
            )

            transaction = _update_transaction(
                store,
                transaction,
                status="committed",
                details={
                    "previous_active_version": previous_active,
                    "active_version": target_version,
                    "inventory_revision": inventory.revision,
                    "active_pointer": str(pointer_path),
                },
            )

        return {
            "status": "rolled_back",
            "transaction_id": transaction_id,
            "plugin_id": plugin_id,
            "previous_active_version": previous_active,
            "active_version": target_version,
            "installed_path": str(installed_path),
        }

    except Exception as exc:
        recovery_errors: list[str] = []
        if original_inventory is not None:
            try:
                store.save_inventory(original_inventory)
            except (OSError, TypeError, ValueError) as recovery_exc:
                recovery_errors.append(
                    f"inventory restore failed: {recovery_exc}"
                )

        if previous_pointer is None:
            pointer_path.unlink(missing_ok=True)
        else:
            try:
                pointer_path.write_text(
                    previous_pointer,
                    encoding="utf-8",
                )
            except OSError as recovery_exc:
                recovery_errors.append(
                    f"pointer restore failed: {recovery_exc}"
                )

        _update_transaction(
            store,
            transaction,
            status="failed",
            details={
                "error_type": type(exc).__name__,
                "error": str(exc),
                "recovery_errors": recovery_errors,
            },
        )
        raise
