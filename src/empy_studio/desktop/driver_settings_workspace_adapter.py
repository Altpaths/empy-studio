from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.core import (
    DriverConfiguration,
    DriverCredentialMode,
    DriverSettings,
)
from empy_studio.drivers import DriverRegistry


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


class DriverSettingsWorkspaceAdapter:
    """Persist provider settings without storing credential secrets."""

    def __init__(
        self,
        workspace_root: str | Path,
        registry: DriverRegistry,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace_root / "driver-settings.json"
        self.registry = registry

    def load(self) -> DriverSettings:
        if not self.path.is_file():
            return self.registry.default_settings()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("driver settings must contain an object")
        raw_providers = value.get("providers")
        if not isinstance(raw_providers, list):
            raise TypeError("driver settings providers must be a list")
        providers: list[DriverConfiguration] = []
        for raw in raw_providers:
            if not isinstance(raw, dict):
                continue
            providers.append(
                DriverConfiguration(
                    provider_id=str(raw["provider_id"]),
                    enabled=bool(raw["enabled"]),
                    executable=_optional_string(raw.get("executable")),
                    credential_mode=cast(
                        DriverCredentialMode,
                        str(raw["credential_mode"]),
                    ),
                    credential_environment_variable=_optional_string(
                        raw.get("credential_environment_variable")
                    ),
                )
            )
        loaded = {
            configuration.provider_id: configuration
            for configuration in providers
        }
        for provider_id in loaded:
            self.registry.definition(provider_id)
        defaults = self.registry.default_settings()
        merged = tuple(
            loaded.get(item.provider_id, item)
            for item in defaults.providers
        )
        settings = DriverSettings(
            schema_version=_as_int(value["schema_version"], "schema_version"),
            default_provider=str(value["default_provider"]),
            providers=merged,
        )
        settings.validate()
        return settings

    def save(self, settings: DriverSettings) -> None:
        settings.validate()
        for configuration in settings.providers:
            self.registry.definition(configuration.provider_id)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                settings.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
