from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

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


def list_plugins(store_root: str | Path) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()
    inventory = store.load_inventory()

    plugins = []
    for plugin_id, entry in sorted(inventory.plugins.items()):
        versions = []
        for version, record in sorted(entry.versions.items()):
            installed_path = store.root / record.path
            versions.append(
                {
                    "version": version,
                    "active": version == entry.active_version,
                    "path": record.path,
                    "path_exists": installed_path.is_dir(),
                    "package_sha256": record.package_sha256,
                    "source": record.source,
                    "installed_at": record.installed_at,
                }
            )

        plugins.append(
            {
                "plugin_id": plugin_id,
                "active_version": entry.active_version,
                "version_count": len(versions),
                "versions": versions,
            }
        )

    return {
        "status": "ok",
        "store_root": str(store.root),
        "inventory_revision": inventory.revision,
        "plugin_count": len(plugins),
        "plugins": plugins,
    }


def plugin_store_status(
    store_root: str | Path,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()
    inventory = store.load_inventory()

    issues: list[dict[str, str]] = []

    for plugin_id, entry in sorted(inventory.plugins.items()):
        pointer_path = store.active_path / f"{plugin_id}.json"

        if entry.active_version is None:
            issues.append(
                {
                    "plugin_id": plugin_id,
                    "error_type": "missing_active_version",
                    "message": "Plugin has no active version",
                }
            )
        elif not pointer_path.is_file():
            issues.append(
                {
                    "plugin_id": plugin_id,
                    "error_type": "missing_active_pointer",
                    "message": str(pointer_path),
                }
            )
        else:
            try:
                pointer = json.loads(
                    pointer_path.read_text(encoding="utf-8")
                )
                if not isinstance(pointer, dict):
                    raise TypeError(
                        "Active pointer must contain a JSON object"
                    )
                if pointer.get("version") != entry.active_version:
                    issues.append(
                        {
                            "plugin_id": plugin_id,
                            "error_type": "pointer_version_mismatch",
                            "message": (
                                f"Inventory active version is "
                                f"{entry.active_version}; pointer is "
                                f"{pointer.get('version')}"
                            ),
                        }
                    )
            except (
                json.JSONDecodeError,
                TypeError,
            ) as exc:
                issues.append(
                    {
                        "plugin_id": plugin_id,
                        "error_type": "invalid_active_pointer",
                        "message": str(exc),
                    }
                )

        for version, record in sorted(entry.versions.items()):
            installed_path = store.root / record.path
            if not installed_path.is_dir():
                issues.append(
                    {
                        "plugin_id": plugin_id,
                        "error_type": "missing_installed_path",
                        "message": (
                            f"Version {version} path is missing: "
                            f"{installed_path}"
                        ),
                    }
                )
                continue

            if not (installed_path / "plugin.json").is_file():
                issues.append(
                    {
                        "plugin_id": plugin_id,
                        "error_type": "missing_manifest",
                        "message": (
                            f"Version {version} has no plugin.json"
                        ),
                    }
                )

            if not (installed_path / "payload").is_dir():
                issues.append(
                    {
                        "plugin_id": plugin_id,
                        "error_type": "missing_payload",
                        "message": (
                            f"Version {version} has no payload directory"
                        ),
                    }
                )

    return {
        "status": "healthy" if not issues else "degraded",
        "store_root": str(store.root),
        "inventory_revision": inventory.revision,
        "plugin_count": len(inventory.plugins),
        "issue_count": len(issues),
        "issues": issues,
    }


def remove_plugin_version(
    plugin_id: str,
    version: str,
    store_root: str | Path,
    *,
    replacement_version: str | None = None,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()

    transaction_id = f"remove-{uuid.uuid4().hex}"
    timestamp = utc_now()
    transaction = TransactionRecord(
        transaction_id=transaction_id,
        operation="remove",
        plugin_id=plugin_id,
        version=version,
        status="created",
        created_at=timestamp,
        updated_at=timestamp,
        details={
            "replacement_version": replacement_version,
        },
    )
    store.write_transaction(transaction)

    original_inventory: PluginInventory | None = None
    pointer_path = store.active_path / f"{plugin_id}.json"
    previous_pointer: str | None = None
    removed_path: Path | None = None
    backup_path: Path | None = None

    try:
        with store.lock():
            inventory = store.load_inventory()
            original_inventory = _copy_inventory(inventory)

            entry = inventory.plugins.get(plugin_id)
            if entry is None:
                raise KeyError(
                    f"Plugin is not installed: {plugin_id}"
                )

            record = entry.versions.get(version)
            if record is None:
                raise ValueError(
                    f"Plugin {plugin_id} version {version} "
                    f"is not installed"
                )

            is_active = entry.active_version == version

            if is_active:
                if replacement_version is None:
                    remaining = sorted(
                        candidate
                        for candidate in entry.versions
                        if candidate != version
                    )
                    if remaining:
                        raise ValueError(
                            "Cannot remove the active version without "
                            "a replacement_version"
                        )
                elif replacement_version not in entry.versions:
                    raise ValueError(
                        f"Replacement version {replacement_version} "
                        f"is not installed"
                    )
                elif replacement_version == version:
                    raise ValueError(
                        "Replacement version must differ from removed version"
                    )

            if pointer_path.is_file():
                previous_pointer = pointer_path.read_text(
                    encoding="utf-8"
                )

            installed_path = store.root / record.path
            if not installed_path.is_dir():
                raise FileNotFoundError(installed_path)

            backup_path = (
                store.root
                / ".trash"
                / transaction_id
                / plugin_id
                / version
            )
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(installed_path, backup_path)
            removed_path = installed_path

            del entry.versions[version]

            if is_active:
                entry.active_version = replacement_version

            if not entry.versions:
                del inventory.plugins[plugin_id]
                pointer_path.unlink(missing_ok=True)
            elif entry.active_version is not None:
                active_record = entry.versions[
                    entry.active_version
                ]
                _write_json_atomic(
                    pointer_path,
                    {
                        "plugin_id": plugin_id,
                        "version": entry.active_version,
                        "path": active_record.path,
                        "updated_at": utc_now(),
                    },
                )

            inventory.revision += 1
            store.save_inventory(inventory)

            transaction = _update_transaction(
                store,
                transaction,
                status="committed",
                details={
                    "removed_version": version,
                    "replacement_version": replacement_version,
                    "inventory_revision": inventory.revision,
                },
            )

        if backup_path is not None:
            shutil.rmtree(
                backup_path.parent.parent.parent,
                ignore_errors=True,
            )

        return {
            "status": "removed",
            "transaction_id": transaction_id,
            "plugin_id": plugin_id,
            "removed_version": version,
            "active_version": replacement_version,
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

        if (
            backup_path is not None
            and backup_path.exists()
            and removed_path is not None
        ):
            removed_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            try:
                os.replace(backup_path, removed_path)
            except OSError as recovery_exc:
                recovery_errors.append(
                    f"file restore failed: {recovery_exc}"
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


def remove_plugin(
    plugin_id: str,
    store_root: str | Path,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()
    inventory = store.load_inventory()

    entry = inventory.plugins.get(plugin_id)
    if entry is None:
        raise KeyError(
            f"Plugin is not installed: {plugin_id}"
        )

    removed_versions: list[str] = []
    for version in sorted(
        entry.versions,
        reverse=True,
    ):
        current = store.load_inventory().plugins.get(plugin_id)
        if current is None:
            break

        replacement = None
        if current.active_version == version:
            remaining = sorted(
                candidate
                for candidate in current.versions
                if candidate != version
            )
            replacement = remaining[-1] if remaining else None

        remove_plugin_version(
            plugin_id,
            version,
            store_root,
            replacement_version=replacement,
        )
        removed_versions.append(version)

    return {
        "status": "removed",
        "plugin_id": plugin_id,
        "removed_versions": sorted(removed_versions),
    }
