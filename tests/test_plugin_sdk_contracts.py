from __future__ import annotations

import pytest

from empy_studio.plugin_manifest import (
    PluginManifest,
    is_compatible,
    parse_version,
)


def valid_manifest() -> dict[str, object]:
    return {
        "plugin_id": "example-plugin",
        "name": "Example Plugin",
        "version": "1.2.0",
        "empy_requires": ">=1.0.0",
        "entrypoint": "example_plugin:Plugin",
        "hooks": ["agent", "validator"],
        "description": "Test plugin",
        "capabilities": ["python"],
    }


def test_manifest_parses_and_validates() -> None:
    manifest = PluginManifest.from_dict(valid_manifest())
    assert manifest.plugin_id == "example-plugin"
    assert manifest.hooks == ("agent", "validator")
    assert manifest.supports("1.1.0")


def test_invalid_plugin_id_is_rejected() -> None:
    data = valid_manifest()
    data["plugin_id"] = "Invalid Plugin"
    with pytest.raises(ValueError, match="plugin_id"):
        PluginManifest.from_dict(data)


def test_unknown_hook_is_rejected() -> None:
    data = valid_manifest()
    data["hooks"] = ["unknown"]
    with pytest.raises(ValueError, match="Unknown plugin hooks"):
        PluginManifest.from_dict(data)


def test_invalid_entrypoint_is_rejected() -> None:
    data = valid_manifest()
    data["entrypoint"] = "example_plugin"
    with pytest.raises(ValueError, match="entrypoint"):
        PluginManifest.from_dict(data)


def test_version_compatibility() -> None:
    assert is_compatible("1.2.0", ">=1.0.0")
    assert is_compatible("1.2.0", "<2.0.0")
    assert not is_compatible("0.9.0", ">=1.0.0")
    assert parse_version("1.0.0")[:3] == (1, 0, 0)


def test_invalid_version_requirement_is_rejected() -> None:
    with pytest.raises(ValueError, match="requirement"):
        is_compatible("1.0.0", "^1.0")
