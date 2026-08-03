from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_FORMAT = "empy-plugin-store-v1"
INVENTORY_NAME = "inventory.json"
LOCK_NAME = ".store.lock"
TRANSACTIONS_DIR = "transactions"
PACKAGES_DIR = "packages"
ACTIVE_DIR = "active"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class InstalledVersion:
    version: str
    package_sha256: str
    installed_at: str
    source: str
    path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstalledVersion:
        return cls(
            version=str(data["version"]),
            package_sha256=str(data["package_sha256"]),
            installed_at=str(data["installed_at"]),
            source=str(data["source"]),
            path=str(data["path"]),
        )


@dataclass
class PluginInventoryEntry:
    plugin_id: str
    active_version: str | None = None
    versions: dict[str, InstalledVersion] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        plugin_id: str,
        data: dict[str, Any],
    ) -> PluginInventoryEntry:
        raw_versions = data.get("versions", {})
        if not isinstance(raw_versions, dict):
            raise TypeError("Inventory versions must be a JSON object")

        return cls(
            plugin_id=plugin_id,
            active_version=(
                str(data["active_version"])
                if data.get("active_version") is not None
                else None
            ),
            versions={
                str(version): InstalledVersion.from_dict(value)
                for version, value in raw_versions.items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_version": self.active_version,
            "versions": {
                version: asdict(record)
                for version, record in sorted(self.versions.items())
            },
        }


@dataclass
class PluginInventory:
    format: str = STORE_FORMAT
    revision: int = 0
    updated_at: str = field(default_factory=utc_now)
    plugins: dict[str, PluginInventoryEntry] = field(
        default_factory=dict
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginInventory:
        if data.get("format") != STORE_FORMAT:
            raise ValueError("Unsupported plugin store inventory format")

        raw_plugins = data.get("plugins", {})
        if not isinstance(raw_plugins, dict):
            raise TypeError("Inventory plugins must be a JSON object")

        return cls(
            format=STORE_FORMAT,
            revision=int(data.get("revision", 0)),
            updated_at=str(data.get("updated_at", utc_now())),
            plugins={
                str(plugin_id): PluginInventoryEntry.from_dict(
                    str(plugin_id),
                    value,
                )
                for plugin_id, value in raw_plugins.items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "plugins": {
                plugin_id: entry.to_dict()
                for plugin_id, entry in sorted(self.plugins.items())
            },
        }


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    operation: str
    plugin_id: str
    version: str | None
    status: str
    created_at: str
    updated_at: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PluginStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.inventory_path = self.root / INVENTORY_NAME
        self.lock_path = self.root / LOCK_NAME
        self.transactions_path = self.root / TRANSACTIONS_DIR
        self.packages_path = self.root / PACKAGES_DIR
        self.active_path = self.root / ACTIVE_DIR

    def initialize(self) -> PluginInventory:
        self.root.mkdir(parents=True, exist_ok=True)
        self.transactions_path.mkdir(parents=True, exist_ok=True)
        self.packages_path.mkdir(parents=True, exist_ok=True)
        self.active_path.mkdir(parents=True, exist_ok=True)

        if self.inventory_path.exists():
            return self.load_inventory()

        inventory = PluginInventory()
        self.save_inventory(inventory)
        return inventory

    def load_inventory(self) -> PluginInventory:
        if not self.inventory_path.is_file():
            raise FileNotFoundError(self.inventory_path)

        value = json.loads(
            self.inventory_path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError("Inventory must contain a JSON object")

        inventory = PluginInventory.from_dict(value)
        self.validate_inventory(inventory)
        return inventory

    def save_inventory(
        self,
        inventory: PluginInventory,
    ) -> None:
        self.validate_inventory(inventory)
        inventory.updated_at = utc_now()

        self.root.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.root,
            prefix=".inventory-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(
                inventory.to_dict(),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, self.inventory_path)

    def validate_inventory(
        self,
        inventory: PluginInventory,
    ) -> None:
        if inventory.format != STORE_FORMAT:
            raise ValueError("Unsupported plugin store format")
        if inventory.revision < 0:
            raise ValueError("Inventory revision cannot be negative")

        for plugin_id, entry in inventory.plugins.items():
            if plugin_id != entry.plugin_id:
                raise ValueError(
                    f"Inventory key does not match plugin_id: {plugin_id}"
                )

            if (
                entry.active_version is not None
                and entry.active_version not in entry.versions
            ):
                raise ValueError(
                    f"Active version {entry.active_version} is not "
                    f"installed for plugin {plugin_id}"
                )

            for version, record in entry.versions.items():
                if version != record.version:
                    raise ValueError(
                        f"Inventory version key mismatch for {plugin_id}"
                    )

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)

        try:
            descriptor = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise RuntimeError(
                f"Plugin store is locked: {self.lock_path}"
            ) from exc

        try:
            payload = {
                "pid": os.getpid(),
                "created_at": utc_now(),
            }
            os.write(
                descriptor,
                (
                    json.dumps(payload, ensure_ascii=False)
                    + "\n"
                ).encode("utf-8"),
            )
            os.fsync(descriptor)
            yield
        finally:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)

    def transaction_path(self, transaction_id: str) -> Path:
        safe = "".join(
            char
            if char.isalnum() or char in "-_"
            else "_"
            for char in transaction_id
        )
        return self.transactions_path / f"{safe}.json"

    def write_transaction(
        self,
        record: TransactionRecord,
    ) -> Path:
        self.transactions_path.mkdir(
            parents=True,
            exist_ok=True,
        )
        path = self.transaction_path(record.transaction_id)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
        return path

    def read_transaction(
        self,
        transaction_id: str,
    ) -> TransactionRecord:
        path = self.transaction_path(transaction_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(
                "Transaction record must contain a JSON object"
            )

        details = value.get("details", {})
        if not isinstance(details, dict):
            raise TypeError(
                "Transaction details must be a JSON object"
            )

        return TransactionRecord(
            transaction_id=str(value["transaction_id"]),
            operation=str(value["operation"]),
            plugin_id=str(value["plugin_id"]),
            version=(
                str(value["version"])
                if value.get("version") is not None
                else None
            ),
            status=str(value["status"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            details=details,
        )
