from __future__ import annotations

from typing import Any

from empy_studio.plugin_contracts import PluginContext


class Plugin:
    def register_agents(
        self,
        context: PluginContext,
    ) -> list[dict[str, Any]]:
        return [
            {
                "agent_id": "example-agent",
                "project_root": context.project_root,
            }
        ]

    def register_adapters(
        self,
        context: PluginContext,
    ) -> dict[str, dict[str, Any]]:
        return {
            "example-adapter": {
                "project_root": context.project_root,
            }
        }

    def register_validators(
        self,
        context: PluginContext,
    ) -> list[dict[str, Any]]:
        return [
            {
                "validator_id": "example-validator",
                "environment": context.config.get("environment"),
            }
        ]

    def register_context_providers(
        self,
        context: PluginContext,
    ) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": "example-context",
                "project_root": context.project_root,
            }
        ]
