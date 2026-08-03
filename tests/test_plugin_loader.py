from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from empy_studio.plugin_loader import load_installed_plugin


def create_plugin(
    root: Path,
    *,
    plugin_id: str = "example-plugin",
    version: str = "1.0.0",
    empy_requires: str = ">=0.1.0",
    entrypoint: str = "plugin_main:Plugin",
    code: str | None = None,
) -> Path:
    plugin_root = root / plugin_id
    payload = plugin_root / "payload"
    payload.mkdir(parents=True)

    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "name": plugin_id,
                "version": version,
                "empy_requires": empy_requires,
                "entrypoint": entrypoint,
                "hooks": ["agent"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    source = code or (
        "class Plugin:\n"
        "    def __init__(self):\n"
        "        self.ready = True\n"
    )
    (payload / "plugin_main.py").write_text(
        source,
        encoding="utf-8",
    )

    return plugin_root


def test_loads_plugin_class_and_creates_instance(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(tmp_path)

    loaded = load_installed_plugin(
        plugin_root,
        empy_version="1.0.0",
    )

    assert loaded.manifest.plugin_id == "example-plugin"
    assert loaded.instance.ready is True
    assert loaded.module_name.startswith(
        "_empy_plugin_example_plugin_"
    )


def test_loads_object_entrypoint_without_instantiation(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        entrypoint="plugin_main:plugin",
        code=(
            "class PluginObject:\n"
            "    ready = True\n\n"
            "plugin = PluginObject()\n"
        ),
    )

    loaded = load_installed_plugin(
        plugin_root,
        empy_version="1.0.0",
    )

    assert loaded.instance.ready is True


def test_missing_entrypoint_module_is_rejected(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        entrypoint="missing_module:Plugin",
    )

    with pytest.raises(
        ImportError,
        match="Entrypoint module not found",
    ):
        load_installed_plugin(
            plugin_root,
            empy_version="1.0.0",
        )


def test_missing_entrypoint_object_is_rejected(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        entrypoint="plugin_main:Missing",
    )

    with pytest.raises(
        ImportError,
        match="entrypoint object not found",
    ):
        load_installed_plugin(
            plugin_root,
            empy_version="1.0.0",
        )


def test_incompatible_plugin_is_rejected_before_import(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    plugin_root = create_plugin(
        tmp_path,
        empy_requires=">=2.0.0",
        code=(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
            "class Plugin:\n"
            "    pass\n"
        ),
    )

    with pytest.raises(
        ValueError,
        match="current version",
    ):
        load_installed_plugin(
            plugin_root,
            empy_version="1.0.0",
        )

    assert not marker.exists()


def test_failed_import_is_removed_from_sys_modules(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        code="raise RuntimeError('load failed')\n",
    )

    expected_prefix = "_empy_plugin_example_plugin_"
    before = {
        name
        for name in sys.modules
        if name.startswith(expected_prefix)
    }

    with pytest.raises(
        RuntimeError,
        match="load failed",
    ):
        load_installed_plugin(
            plugin_root,
            empy_version="1.0.0",
        )

    after = {
        name
        for name in sys.modules
        if name.startswith(expected_prefix)
    }

    assert after == before


def test_same_module_name_from_two_plugins_is_isolated(
    tmp_path: Path,
) -> None:
    first = create_plugin(
        tmp_path / "first",
        plugin_id="first-plugin",
        code=(
            "class Plugin:\n"
            "    value = 'first'\n"
        ),
    )
    second = create_plugin(
        tmp_path / "second",
        plugin_id="second-plugin",
        code=(
            "class Plugin:\n"
            "    value = 'second'\n"
        ),
    )

    first_loaded = load_installed_plugin(
        first,
        empy_version="1.0.0",
    )
    second_loaded = load_installed_plugin(
        second,
        empy_version="1.0.0",
    )

    assert first_loaded.module_name != second_loaded.module_name
    assert first_loaded.instance.value == "first"
    assert second_loaded.instance.value == "second"
