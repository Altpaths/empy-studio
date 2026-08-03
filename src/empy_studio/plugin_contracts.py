from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

PluginHook = Literal[
    "agent",
    "adapter",
    "validator",
    "context_provider",
]


@dataclass(frozen=True)
class PluginContext:
    project_root: str
    config: dict[str, Any]


@runtime_checkable
class AgentPluginHook(Protocol):
    def register_agents(self, context: PluginContext) -> list[Any]:
        ...


@runtime_checkable
class AdapterPluginHook(Protocol):
    def register_adapters(self, context: PluginContext) -> dict[str, Any]:
        ...


@runtime_checkable
class ValidatorPluginHook(Protocol):
    def register_validators(self, context: PluginContext) -> list[Any]:
        ...


@runtime_checkable
class ContextProviderPluginHook(Protocol):
    def register_context_providers(self, context: PluginContext) -> list[Any]:
        ...
