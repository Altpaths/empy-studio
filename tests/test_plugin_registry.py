from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.plugin_contracts import PluginContext
from empy_studio.plugin_loader import load_installed_plugin
from empy_studio.plugin_registry import HookRegistry


def create_plugin(
    root: Path,
    *,
    plugin_id: str = "example-plugin",
    hooks: list[str] | None = None,
    code: str,
) -> Path:
    plugin_root = root / plugin_id
    payload = plugin_root / "payload"
    payload.mkdir(parents=True)

    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "name": plugin_id,
                "version": "1.0.0",
                "empy_requires": ">=0.1.0",
                "entrypoint": "plugin_main:Plugin",
                "hooks": hooks or [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (payload / "plugin_main.py").write_text(
        code,
        encoding="utf-8",
    )
    return plugin_root


def load(
    plugin_root: Path,
):
    return load_installed_plugin(
        plugin_root,
        empy_version="1.0.0",
    )


def context(tmp_path: Path) -> PluginContext:
    return PluginContext(
        project_root=str(tmp_path),
        config={"environment": "test"},
    )


def test_registers_all_supported_hooks(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        hooks=[
            "agent",
            "adapter",
            "validator",
            "context_provider",
        ],
        code=(
            "class Plugin:\n"
            "    def register_agents(self, context):\n"
            "        return [{'agent_id': 'agent-a'}]\n\n"
            "    def register_adapters(self, context):\n"
            "        return {'adapter-a': {'ready': True}}\n\n"
            "    def register_validators(self, context):\n"
            "        return [{'validator_id': 'validator-a'}]\n\n"
            "    def register_context_providers(self, context):\n"
            "        return [{'provider_id': 'provider-a'}]\n"
        ),
    )

    registry = HookRegistry()
    registry.register(
        load(plugin_root),
        context(tmp_path),
    )

    assert registry.plugins == ["example-plugin"]
    assert registry.agents[0]["agent_id"] == "agent-a"
    assert registry.adapters["adapter-a"]["ready"] is True
    assert (
        registry.validators[0]["validator_id"]
        == "validator-a"
    )
    assert (
        registry.context_providers[0]["provider_id"]
        == "provider-a"
    )
    assert registry.describe() == {
        "plugins": ["example-plugin"],
        "agent_count": 1,
        "adapter_ids": ["adapter-a"],
        "validator_count": 1,
        "context_provider_count": 1,
    }


def test_rejects_duplicate_plugin_registration(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        hooks=[],
        code="class Plugin:\n    pass\n",
    )
    loaded = load(plugin_root)
    registry = HookRegistry()

    registry.register(loaded, context(tmp_path))

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        registry.register(loaded, context(tmp_path))


def test_rejects_missing_declared_hook_method(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        hooks=["validator"],
        code="class Plugin:\n    pass\n",
    )

    registry = HookRegistry()

    with pytest.raises(
        TypeError,
        match="register_validators",
    ):
        registry.register(
            load(plugin_root),
            context(tmp_path),
        )

    assert registry.plugins == []
    assert registry.validators == []


def test_rejects_invalid_hook_return_type(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        hooks=["agent"],
        code=(
            "class Plugin:\n"
            "    def register_agents(self, context):\n"
            "        return {'not': 'a list'}\n"
        ),
    )

    registry = HookRegistry()

    with pytest.raises(
        TypeError,
        match="must return a list",
    ):
        registry.register(
            load(plugin_root),
            context(tmp_path),
        )

    assert registry.plugins == []
    assert registry.agents == []


def test_rejects_duplicate_adapter_ids(
    tmp_path: Path,
) -> None:
    first_root = create_plugin(
        tmp_path / "first",
        plugin_id="first-plugin",
        hooks=["adapter"],
        code=(
            "class Plugin:\n"
            "    def register_adapters(self, context):\n"
            "        return {'shared-adapter': {'owner': 'first'}}\n"
        ),
    )
    second_root = create_plugin(
        tmp_path / "second",
        plugin_id="second-plugin",
        hooks=["adapter"],
        code=(
            "class Plugin:\n"
            "    def register_adapters(self, context):\n"
            "        return {'shared-adapter': {'owner': 'second'}}\n"
        ),
    )

    registry = HookRegistry()
    registry.register(
        load(first_root),
        context(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="Duplicate adapter IDs",
    ):
        registry.register(
            load(second_root),
            context(tmp_path),
        )

    assert registry.plugins == ["first-plugin"]
    assert (
        registry.adapters["shared-adapter"]["owner"]
        == "first"
    )


def test_registration_is_atomic_when_later_hook_fails(
    tmp_path: Path,
) -> None:
    plugin_root = create_plugin(
        tmp_path,
        hooks=["agent", "validator"],
        code=(
            "class Plugin:\n"
            "    def register_agents(self, context):\n"
            "        return [{'agent_id': 'temporary'}]\n\n"
            "    def register_validators(self, context):\n"
            "        return {'invalid': 'type'}\n"
        ),
    )

    registry = HookRegistry()

    with pytest.raises(TypeError):
        registry.register(
            load(plugin_root),
            context(tmp_path),
        )

    assert registry.plugins == []
    assert registry.agents == []
    assert registry.validators == []
