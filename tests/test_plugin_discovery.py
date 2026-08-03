from __future__ import annotations

import json
from pathlib import Path

from empy_studio.plugin_discovery import discover_installed_plugins


def create_plugin(
    store: Path,
    *,
    directory: str,
    plugin_id: str,
    empy_requires: str = ">=0.1.0",
    payload_code: str = "PLUGIN_IMPORTED = True\n",
) -> Path:
    plugin_root = store / directory
    payload = plugin_root / "payload"
    payload.mkdir(parents=True)

    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "name": plugin_id,
                "version": "1.0.0",
                "empy_requires": empy_requires,
                "entrypoint": "plugin_main:Plugin",
                "hooks": ["agent"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (payload / "plugin_main.py").write_text(
        payload_code,
        encoding="utf-8",
    )
    return plugin_root


def test_discovers_valid_plugins_in_stable_order(
    tmp_path: Path,
) -> None:
    store = tmp_path / "plugins"
    create_plugin(
        store,
        directory="z-plugin",
        plugin_id="z-plugin",
    )
    create_plugin(
        store,
        directory="a-plugin",
        plugin_id="a-plugin",
    )

    result = discover_installed_plugins(
        [store],
        empy_version="1.0.0",
    )

    assert result["status"] == "ok"
    assert result["plugin_count"] == 2
    assert result["issue_count"] == 0
    assert [
        item["manifest"]["plugin_id"]
        for item in result["plugins"]
    ] == ["a-plugin", "z-plugin"]


def test_discovery_never_imports_plugin_code(
    tmp_path: Path,
) -> None:
    store = tmp_path / "plugins"
    marker = tmp_path / "plugin-executed"

    create_plugin(
        store,
        directory="dangerous-plugin",
        plugin_id="dangerous-plugin",
        payload_code=(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
        ),
    )

    result = discover_installed_plugins(
        [store],
        empy_version="1.0.0",
    )

    assert result["plugin_count"] == 1
    assert not marker.exists()


def test_reports_invalid_json_without_stopping_other_plugins(
    tmp_path: Path,
) -> None:
    store = tmp_path / "plugins"
    create_plugin(
        store,
        directory="valid",
        plugin_id="valid-plugin",
    )

    invalid = store / "invalid"
    invalid.mkdir(parents=True)
    (invalid / "plugin.json").write_text(
        "{not-json",
        encoding="utf-8",
    )

    result = discover_installed_plugins(
        [store],
        empy_version="1.0.0",
    )

    assert result["status"] == "partial"
    assert result["plugin_count"] == 1
    assert result["issue_count"] == 1
    assert result["issues"][0]["error_type"] == "invalid_json"


def test_reports_incompatible_plugin(
    tmp_path: Path,
) -> None:
    store = tmp_path / "plugins"
    create_plugin(
        store,
        directory="future-plugin",
        plugin_id="future-plugin",
        empy_requires=">=2.0.0",
    )

    result = discover_installed_plugins(
        [store],
        empy_version="1.0.0",
    )

    assert result["plugin_count"] == 0
    assert result["issue_count"] == 1
    assert result["issues"][0]["error_type"] == "invalid_manifest"
    assert "current version" in result["issues"][0]["message"]


def test_duplicate_plugin_ids_are_reported(
    tmp_path: Path,
) -> None:
    first_store = tmp_path / "first"
    second_store = tmp_path / "second"

    create_plugin(
        first_store,
        directory="plugin",
        plugin_id="duplicate-plugin",
    )
    create_plugin(
        second_store,
        directory="plugin",
        plugin_id="duplicate-plugin",
    )

    result = discover_installed_plugins(
        [first_store, second_store],
        empy_version="1.0.0",
    )

    assert result["plugin_count"] == 1
    assert result["issue_count"] == 1
    assert "Duplicate plugin_id" in result["issues"][0]["message"]


def test_missing_discovery_root_is_reported(
    tmp_path: Path,
) -> None:
    result = discover_installed_plugins(
        [tmp_path / "missing"],
        empy_version="1.0.0",
    )

    assert result["status"] == "partial"
    assert result["plugin_count"] == 0
    assert result["issues"][0]["error_type"] == "missing_root"
