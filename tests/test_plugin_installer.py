from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from empy_studio.plugin_installer import install_plugin
from empy_studio.plugin_package import build_package
from empy_studio.plugin_store import PluginStore


def create_package(
    tmp_path: Path,
    *,
    plugin_id: str = "example-plugin",
    version: str = "1.0.0",
) -> Path:
    source = tmp_path / f"source-{plugin_id}-{version}"
    payload = source / "payload"
    payload.mkdir(parents=True)

    (source / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "name": plugin_id,
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
        "class Plugin:\n    pass\n",
        encoding="utf-8",
    )

    return build_package(
        source,
        tmp_path / f"{plugin_id}-{version}.empy-plugin",
    )


def test_installs_verified_package_transactionally(
    tmp_path: Path,
) -> None:
    package = create_package(tmp_path)
    store_root = tmp_path / "store"

    result = install_plugin(
        str(package),
        store_root,
        empy_version="1.0.0",
    )

    assert result["status"] == "installed"
    assert result["plugin_id"] == "example-plugin"
    assert result["version"] == "1.0.0"

    store = PluginStore(store_root)
    inventory = store.load_inventory()
    entry = inventory.plugins["example-plugin"]

    assert entry.active_version == "1.0.0"
    assert "1.0.0" in entry.versions

    installed = (
        store_root
        / entry.versions["1.0.0"].path
    )
    assert (installed / "plugin.json").is_file()
    assert (installed / "payload/plugin_main.py").is_file()

    pointer = json.loads(
        (
            store.active_path / "example-plugin.json"
        ).read_text(encoding="utf-8")
    )
    assert pointer["version"] == "1.0.0"


def test_rejects_duplicate_installed_version(
    tmp_path: Path,
) -> None:
    package = create_package(tmp_path)
    store_root = tmp_path / "store"

    install_plugin(
        str(package),
        store_root,
        empy_version="1.0.0",
    )

    with pytest.raises(
        ValueError,
        match="already installed",
    ):
        install_plugin(
            str(package),
            store_root,
            empy_version="1.0.0",
        )

    inventory = PluginStore(store_root).load_inventory()
    assert inventory.revision == 1


def test_records_committed_transaction(
    tmp_path: Path,
) -> None:
    package = create_package(tmp_path)
    store_root = tmp_path / "store"

    result = install_plugin(
        str(package),
        store_root,
        empy_version="1.0.0",
    )

    store = PluginStore(store_root)
    transaction = store.read_transaction(
        result["transaction_id"]
    )

    assert transaction.status == "committed"
    assert transaction.plugin_id == "example-plugin"
    assert transaction.version == "1.0.0"
    assert "installed_path" in transaction.details


def test_failed_install_records_failure_and_leaves_store_clean(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.empy-plugin"
    invalid.write_bytes(b"not-a-zip")
    store_root = tmp_path / "store"

    with pytest.raises(zipfile.BadZipFile):
        install_plugin(
            str(invalid),
            store_root,
            empy_version="1.0.0",
        )

    store = PluginStore(store_root)
    inventory = store.load_inventory()

    assert inventory.plugins == {}
    assert list(store.packages_path.rglob("plugin.json")) == []

    transactions = list(
        store.transactions_path.glob("*.json")
    )
    assert len(transactions) == 1

    value = json.loads(
        transactions[0].read_text(encoding="utf-8")
    )
    assert value["status"] == "failed"


def test_rolls_back_inventory_when_active_pointer_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = create_package(tmp_path)
    store_root = tmp_path / "store"

    def fail_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        destination_path = Path(destination)
        if destination_path.name == "example-plugin.json":
            raise OSError("pointer write failed")


        original_replace(source, destination)

    import os

    original_replace = os.replace
    monkeypatch.setattr(
        "empy_studio.plugin_installer.os.replace",
        fail_replace,
    )

    with pytest.raises(
        OSError,
        match="pointer write failed",
    ):
        install_plugin(
            str(package),
            store_root,
            empy_version="1.0.0",
        )

    store = PluginStore(store_root)
    inventory = store.load_inventory()

    assert inventory.plugins == {}
    assert not (
        store.active_path / "example-plugin.json"
    ).exists()
    assert not (
        store.packages_path
        / "example-plugin"
        / "1.0.0"
    ).exists()


def test_rejects_unexpected_archive_member(
    tmp_path: Path,
) -> None:
    package = create_package(tmp_path)


    unsafe = tmp_path / "unsafe.empy-plugin"
    with zipfile.ZipFile(package, "r") as source:
        members = {
            name: source.read(name)
            for name in source.namelist()
        }

    members["unexpected.txt"] = b"unexpected"

    with zipfile.ZipFile(unsafe, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)

    with pytest.raises(
        ValueError,
        match="Unexpected package member",
    ):
        install_plugin(
            str(unsafe),
            tmp_path / "store",
            empy_version="1.0.0",
        )
