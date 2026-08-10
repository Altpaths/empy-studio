from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from empy_studio.core import (
    DriverAvailability,
    DriverCapabilities,
    DriverCapabilityEntry,
    DriverConfiguration,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverInspection,
    DriverSettings,
    DriverStatus,
)

from .base import BaseDriver
from .claude import ClaudeCodeDriver
from .codex import CodexDriver

DriverFactory = Callable[[DriverConfiguration, Path], BaseDriver]


@dataclass(frozen=True)
class DriverDefinition:
    provider_id: str
    display_name: str
    description: str
    capabilities: DriverCapabilities
    implemented: bool
    default_configuration: DriverConfiguration
    factory: DriverFactory | None = None

    def validate(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        if not self.description.strip():
            raise ValueError("driver description cannot be empty")
        self.default_configuration.validate()
        if self.default_configuration.provider_id != self.provider_id:
            raise ValueError("driver definition and configuration do not match")
        if self.implemented and self.factory is None:
            raise ValueError("implemented driver requires a factory")

    def capability_entry(self) -> DriverCapabilityEntry:
        entry = DriverCapabilityEntry(
            provider_id=self.provider_id,
            display_name=self.display_name,
            implemented=self.implemented,
            capabilities=self.capabilities,
            description=self.description,
        )
        entry.validate()
        return entry


class UnavailableDriver(BaseDriver):
    """Provider placeholder that reports an honest unavailable state."""

    def __init__(
        self,
        *,
        definition: DriverDefinition,
        configuration: DriverConfiguration,
    ) -> None:
        self.definition = definition
        self.configuration = configuration

    @property
    def provider_id(self) -> str:
        return self.definition.provider_id

    @property
    def display_name(self) -> str:
        return self.definition.display_name

    def capabilities(self) -> DriverCapabilities:
        return self.definition.capabilities

    def status(self) -> DriverStatus:
        return "unavailable"

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        del refresh
        availability: DriverAvailability = (
            "disabled"
            if not self.configuration.enabled
            else "unavailable"
        )
        message = (
            f"{self.display_name} is disabled in Empy Studio settings."
            if availability == "disabled"
            else (
                f"{self.display_name} integration is not implemented in "
                "this product ticket."
            )
        )
        inspection = DriverInspection(
            provider_id=self.provider_id,
            display_name=self.display_name,
            availability=availability,
            implemented=False,
            enabled=self.configuration.enabled,
            executable=self.configuration.executable,
            version=None,
            authenticated=False,
            message=message,
            remediation=(
                "Enable the provider after its driver package is installed."
                if availability == "disabled"
                else "Use Codex or install a future compatible driver."
            ),
        )
        inspection.validate()
        return inspection

    def execute(
        self,
        request: DriverExecutionRequest,
    ) -> DriverExecutionResult:
        request.validate()
        result = DriverExecutionResult(
            status="unavailable",
            return_code=None,
            summary=self.inspect().message,
        )
        result.validate()
        return result


def _codex_factory(
    configuration: DriverConfiguration,
    artifact_root: Path,
) -> BaseDriver:
    return CodexDriver(
        executable=configuration.executable or "codex",
        artifact_root=artifact_root,
        enabled=configuration.enabled,
    )


def _claude_factory(
    configuration: DriverConfiguration,
    artifact_root: Path,
) -> BaseDriver:
    del artifact_root
    return ClaudeCodeDriver(
        executable=configuration.executable or "claude",
        enabled=configuration.enabled,
        credential_environment_variable=(
            configuration.credential_environment_variable
            or "ANTHROPIC_API_KEY"
        ),
    )


class DriverRegistry:
    """Provider-neutral registry, factory, and capability matrix."""

    def __init__(
        self,
        definitions: tuple[DriverDefinition, ...] = (),
    ) -> None:
        self._definitions: dict[str, DriverDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: DriverDefinition) -> None:
        definition.validate()
        if definition.provider_id in self._definitions:
            raise ValueError(
                f"driver already registered: {definition.provider_id}"
            )
        self._definitions[definition.provider_id] = definition

    def definitions(self) -> tuple[DriverDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions)
        )

    def definition(self, provider_id: str) -> DriverDefinition:
        try:
            return self._definitions[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown driver provider: {provider_id}") from exc

    def default_settings(self) -> DriverSettings:
        if not self._definitions:
            raise RuntimeError("driver registry is empty")
        preferred = (
            "codex"
            if "codex" in self._definitions
            else next(iter(sorted(self._definitions)))
        )
        providers = tuple(
            self._definitions[key].default_configuration
            for key in sorted(self._definitions)
        )
        settings = DriverSettings(
            schema_version=1,
            default_provider=preferred,
            providers=providers,
        )
        settings.validate()
        return settings

    def capability_matrix(self) -> tuple[DriverCapabilityEntry, ...]:
        return tuple(
            definition.capability_entry()
            for definition in self.definitions()
        )

    def create(
        self,
        configuration: DriverConfiguration,
        *,
        artifact_root: str | Path,
    ) -> BaseDriver:
        configuration.validate()
        definition = self.definition(configuration.provider_id)
        root = Path(artifact_root).expanduser().resolve()
        if definition.factory is None or not definition.implemented:
            return UnavailableDriver(
                definition=definition,
                configuration=configuration,
            )
        return definition.factory(configuration, root)


class DriverManager:
    """Resolve the selected provider without coupling callers to Codex."""

    def __init__(
        self,
        *,
        registry: DriverRegistry,
        settings: DriverSettings,
        artifact_root: str | Path,
    ) -> None:
        settings.validate()
        for configuration in settings.providers:
            registry.definition(configuration.provider_id)
        self.registry = registry
        self.settings = settings
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._instances: dict[str, BaseDriver] = {}

    @property
    def default_provider(self) -> str:
        return self.settings.default_provider

    def driver(self, provider_id: str | None = None) -> BaseDriver:
        selected = provider_id or self.default_provider
        if selected not in self._instances:
            configuration = self.settings.configuration_for(selected)
            self._instances[selected] = self.registry.create(
                configuration,
                artifact_root=self.artifact_root / selected,
            )
        return self._instances[selected]

    def inspections(
        self,
        *,
        refresh: bool = False,
    ) -> tuple[DriverInspection, ...]:
        values: list[DriverInspection] = []
        for definition in self.registry.definitions():
            values.append(
                self.driver(definition.provider_id).inspect(
                    refresh=refresh
                )
            )
        return tuple(values)

    def replace_settings(self, settings: DriverSettings) -> None:
        settings.validate()
        for configuration in settings.providers:
            self.registry.definition(configuration.provider_id)
        self.settings = settings
        self._instances.clear()


def default_driver_registry() -> DriverRegistry:
    none = DriverCapabilities(
        planning=False,
        code_editing=False,
        verification=False,
        streaming=False,
        cancellation=False,
    )
    registry = DriverRegistry()
    registry.register(
        DriverDefinition(
            provider_id="codex",
            display_name="Codex",
            description=(
                "Production CLI driver for bounded code editing, streaming, "
                "verification, and cancellation."
            ),
            capabilities=DriverCapabilities(
                planning=False,
                code_editing=True,
                verification=True,
                streaming=True,
                cancellation=True,
            ),
            implemented=True,
            default_configuration=DriverConfiguration(
                provider_id="codex",
                enabled=True,
                executable="codex",
                credential_mode="cli_login",
            ),
            factory=_codex_factory,
        )
    )
    registry.register(
        DriverDefinition(
            provider_id="claude",
            display_name="Claude",
            description=(
                "Claude Code CLI driver using an external credential, bounded "
                "edit permissions, timeout, and cancellation."
            ),
            capabilities=DriverCapabilities(
                planning=False,
                code_editing=True,
                verification=False,
                streaming=False,
                cancellation=True,
            ),
            implemented=True,
            default_configuration=DriverConfiguration(
                provider_id="claude",
                enabled=False,
                executable="claude",
                credential_mode="environment",
                credential_environment_variable="ANTHROPIC_API_KEY",
            ),
            factory=_claude_factory,
        )
    )
    registry.register(
        DriverDefinition(
            provider_id="gemini",
            display_name="Gemini",
            description=(
                "Reserved provider slot. Execution is unavailable until a "
                "compatible driver is implemented."
            ),
            capabilities=none,
            implemented=False,
            default_configuration=DriverConfiguration(
                provider_id="gemini",
                enabled=False,
                executable="gemini",
                credential_mode="none",
            ),
        )
    )
    return registry
