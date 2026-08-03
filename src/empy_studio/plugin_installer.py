from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .plugin_package import (
    MANIFEST_NAME,
    RECORD_NAME,
    SIGNATURE_NAME,
    inspect_package,
)
from .plugin_source import resolve_plugin_source
from .plugin_store import (
    InstalledVersion,
    PluginInventory,
    PluginInventoryEntry,
    PluginStore,
    TransactionRecord,
    utc_now,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _copy_inventory(inventory: PluginInventory) -> PluginInventory:
    return PluginInventory.from_dict(inventory.to_dict())


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


def _safe_extract_package(
    package_path: Path,
    destination: Path,
) -> None:
    allowed_top_level = {
        MANIFEST_NAME,
        RECORD_NAME,
        SIGNATURE_NAME,
        "payload",
    }

    destination.mkdir(parents=True, exist_ok=False)

    with zipfile.ZipFile(package_path, "r") as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)

            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(
                    f"Unsafe package path: {member.filename}"
                )

            if not member_path.parts:
                continue

            if member_path.parts[0] not in allowed_top_level:
                raise ValueError(
                    f"Unexpected package member: {member.filename}"
                )

            target = destination.joinpath(*member_path.parts)
            resolved_target = target.resolve()
            if destination.resolve() not in resolved_target.parents:
                raise ValueError(
                    f"Package member escapes staging directory: "
                    f"{member.filename}"
                )

            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def install_plugin(
    source: str,
    store_root: str | Path,
    *,
    empy_version: str,
    timeout_seconds: float = 30.0,
    max_bytes: int = 100 * 1024 * 1024,
) -> dict[str, Any]:
    store = PluginStore(store_root)
    store.initialize()

    transaction_id = f"install-{uuid.uuid4().hex}"
    created_at = utc_now()
    transaction = TransactionRecord(
        transaction_id=transaction_id,
        operation="install",
        plugin_id="pending",
        version=None,
        status="created",
        created_at=created_at,
        updated_at=created_at,
        details={"source": source},
    )
    store.write_transaction(transaction)

    cache_dir = store.root / ".cache" / transaction_id
    staging_root = store.root / ".staging" / transaction_id
    final_path: Path | None = None
    active_pointer: Path | None = None
    original_inventory: PluginInventory | None = None
    inventory_saved = False

    try:
        transaction = _update_transaction(
            store,
            transaction,
            status="resolving",
        )

        resolved = resolve_plugin_source(
            source,
            cache_dir,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        package_path = Path(resolved.local_path)

        inspection = inspect_package(
            package_path,
            empy_version=empy_version,
        )
        manifest = inspection.manifest

        transaction = replace(
            transaction,
            plugin_id=manifest.plugin_id,
            version=manifest.version,
        )
        transaction = _update_transaction(
            store,
            transaction,
            status="verified",
            details={
                "resolved_source_type": resolved.source_type,
                "resolved_sha256": resolved.sha256,
                "resolved_size_bytes": resolved.size_bytes,
                "signed": inspection.signed,
            },
        )

        with store.lock():
            inventory = store.load_inventory()
            original_inventory = _copy_inventory(inventory)

            existing_entry = inventory.plugins.get(
                manifest.plugin_id
            )
            if (
                existing_entry is not None
                and manifest.version in existing_entry.versions
            ):
                raise ValueError(
                    f"Plugin {manifest.plugin_id} version "
                    f"{manifest.version} is already installed"
                )

            stage_path = staging_root / manifest.plugin_id / manifest.version
            _safe_extract_package(package_path, stage_path)

            staged_inspection = inspect_package(
                package_path,
                empy_version=empy_version,
            )
            if staged_inspection.manifest != manifest:
                raise ValueError(
                    "Plugin manifest changed during staging"
                )

            transaction = _update_transaction(
                store,
                transaction,
                status="staged",
                details={"staging_path": str(stage_path)},
            )

            final_path = (
                store.packages_path
                / manifest.plugin_id
                / manifest.version
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                raise FileExistsError(final_path)

            os.replace(stage_path, final_path)

            record = InstalledVersion(
                version=manifest.version,
                package_sha256=_sha256_file(package_path),
                installed_at=utc_now(),
                source=source,
                path=str(
                    final_path.relative_to(store.root).as_posix()
                ),
            )

            entry = inventory.plugins.get(manifest.plugin_id)
            if entry is None:
                entry = PluginInventoryEntry(
                    plugin_id=manifest.plugin_id,
                )
                inventory.plugins[manifest.plugin_id] = entry

            entry.versions[manifest.version] = record
            entry.active_version = manifest.version
            inventory.revision += 1

            store.save_inventory(inventory)
            inventory_saved = True

            active_pointer = (
                store.active_path / f"{manifest.plugin_id}.json"
            )
            _write_json_atomic(
                active_pointer,
                {
                    "plugin_id": manifest.plugin_id,
                    "version": manifest.version,
                    "path": record.path,
                    "updated_at": utc_now(),
                },
            )

            transaction = _update_transaction(
                store,
                transaction,
                status="committed",
                details={
                    "installed_path": str(final_path),
                    "active_pointer": str(active_pointer),
                    "inventory_revision": inventory.revision,
                },
            )

        return {
            "status": "installed",
            "transaction_id": transaction_id,
            "plugin_id": manifest.plugin_id,
            "version": manifest.version,
            "installed_path": str(final_path),
            "active": True,
            "package_sha256": resolved.sha256,
        }

    except Exception as exc:
        recovery_errors: list[str] = []

        if inventory_saved and original_inventory is not None:
            try:
                store.save_inventory(original_inventory)
            except (OSError, TypeError, ValueError) as recovery_exc:
                recovery_errors.append(
                    f"inventory restore failed: {recovery_exc}"
                )

        if active_pointer is not None:
            active_pointer.unlink(missing_ok=True)

        if final_path is not None and final_path.exists():
            shutil.rmtree(final_path, ignore_errors=True)

        shutil.rmtree(staging_root, ignore_errors=True)

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

    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)
        shutil.rmtree(staging_root, ignore_errors=True)
