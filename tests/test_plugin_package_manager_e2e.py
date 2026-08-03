from __future__ import annotations

import json
from pathlib import Path

from empy_studio.plugin_lifecycle import (
    rollback_plugin,
    upgrade_plugin,
)
from empy_studio.plugin_management import (
    list_plugins,
    plugin_store_status,
    remove_plugin,
)
from empy_studio.plugin_package import build_package


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


def test_complete_package_manager_lifecycle(
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

    first = upgrade_plugin(
        str(version_one),
        store_root,
        empy_version="1.0.0",
    )
    assert first["version"] == "1.0.0"

    second = upgrade_plugin(
        str(version_two),
        store_root,
        empy_version="1.0.0",
    )
    assert second["previous_active_version"] == "1.0.0"

    listing = list_plugins(store_root)
    assert listing["plugin_count"] == 1
    assert (
        listing["plugins"][0]["active_version"]
        == "2.0.0"
    )
    assert listing["plugins"][0]["version_count"] == 2

    status = plugin_store_status(store_root)
    assert status["status"] == "healthy"

    rolled_back = rollback_plugin(
        "example-plugin",
        "1.0.0",
        store_root,
    )
    assert rolled_back["active_version"] == "1.0.0"

    removed = remove_plugin(
        "example-plugin",
        store_root,
    )
    assert removed["removed_versions"] == [
        "1.0.0",
        "2.0.0",
    ]

    final_listing = list_plugins(store_root)
    assert final_listing["plugin_count"] == 0

    final_status = plugin_store_status(store_root)
    assert final_status["status"] == "healthy"
