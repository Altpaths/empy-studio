from __future__ import annotations

from pathlib import Path

from empy_studio.plugin_contracts import PluginContext
from empy_studio.plugin_loader import load_installed_plugin
from empy_studio.plugin_registry import HookRegistry


def test_reference_plugin_implements_all_hooks() -> None:
    root = Path(
        "examples/plugins/example_plugin"
    ).resolve()

    loaded = load_installed_plugin(
        root,
        empy_version="1.0.0",
    )

    registry = HookRegistry()
    registry.register(
        loaded,
        PluginContext(
            project_root="/tmp/example-project",
            config={"environment": "test"},
        ),
    )

    assert registry.plugins == ["example-plugin"]
    assert registry.agents[0]["agent_id"] == "example-agent"
    assert "example-adapter" in registry.adapters
    assert (
        registry.validators[0]["validator_id"]
        == "example-validator"
    )
    assert (
        registry.context_providers[0]["provider_id"]
        == "example-context"
    )
