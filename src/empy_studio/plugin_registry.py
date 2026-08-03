from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .plugin_contracts import PluginContext
from .plugin_loader import LoadedPlugin


@dataclass
class HookRegistry:
    agents: list[Any] = field(default_factory=list)
    adapters: dict[str, Any] = field(default_factory=dict)
    validators: list[Any] = field(default_factory=list)
    context_providers: list[Any] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)

    def register(
        self,
        loaded: LoadedPlugin,
        context: PluginContext,
    ) -> None:
        plugin_id = loaded.manifest.plugin_id

        if plugin_id in self.plugins:
            raise ValueError(
                f"Plugin is already registered: {plugin_id}"
            )

        pending_agents: list[Any] = []
        pending_adapters: dict[str, Any] = {}
        pending_validators: list[Any] = []
        pending_context_providers: list[Any] = []

        for hook in loaded.manifest.hooks:
            if hook == "agent":
                method = getattr(
                    loaded.instance,
                    "register_agents",
                    None,
                )
                if not callable(method):
                    raise TypeError(
                        f"Plugin {plugin_id} declares the agent hook "
                        f"but does not implement register_agents"
                    )
                values = method(context)
                if not isinstance(values, list):
                    raise TypeError(
                        "register_agents must return a list"
                    )
                pending_agents.extend(values)

            elif hook == "adapter":
                method = getattr(
                    loaded.instance,
                    "register_adapters",
                    None,
                )
                if not callable(method):
                    raise TypeError(
                        f"Plugin {plugin_id} declares the adapter hook "
                        f"but does not implement register_adapters"
                    )
                values = method(context)
                if not isinstance(values, dict):
                    raise TypeError(
                        "register_adapters must return a dictionary"
                    )

                duplicate_ids = sorted(
                    set(values).intersection(self.adapters)
                    | set(values).intersection(pending_adapters)
                )
                if duplicate_ids:
                    raise ValueError(
                        f"Duplicate adapter IDs: {duplicate_ids}"
                    )

                pending_adapters.update(values)

            elif hook == "validator":
                method = getattr(
                    loaded.instance,
                    "register_validators",
                    None,
                )
                if not callable(method):
                    raise TypeError(
                        f"Plugin {plugin_id} declares the validator hook "
                        f"but does not implement register_validators"
                    )
                values = method(context)
                if not isinstance(values, list):
                    raise TypeError(
                        "register_validators must return a list"
                    )
                pending_validators.extend(values)

            elif hook == "context_provider":
                method = getattr(
                    loaded.instance,
                    "register_context_providers",
                    None,
                )
                if not callable(method):
                    raise TypeError(
                        f"Plugin {plugin_id} declares the context-provider "
                        f"hook but does not implement "
                        f"register_context_providers"
                    )
                values = method(context)
                if not isinstance(values, list):
                    raise TypeError(
                        "register_context_providers must return a list"
                    )
                pending_context_providers.extend(values)

        self.agents.extend(pending_agents)
        self.adapters.update(pending_adapters)
        self.validators.extend(pending_validators)
        self.context_providers.extend(
            pending_context_providers
        )
        self.plugins.append(plugin_id)

    def describe(self) -> dict[str, Any]:
        return {
            "plugins": list(self.plugins),
            "agent_count": len(self.agents),
            "adapter_ids": sorted(self.adapters),
            "validator_count": len(self.validators),
            "context_provider_count": len(
                self.context_providers
            ),
        }
