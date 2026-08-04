from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.core import DriverConfiguration, DriverSettings
from empy_studio.desktop.driver_settings_workspace_adapter import (
    DriverSettingsWorkspaceAdapter,
)
from empy_studio.drivers import default_driver_registry


def test_returns_registry_defaults_before_first_save(tmp_path: Path) -> None:
    registry = default_driver_registry()
    store = DriverSettingsWorkspaceAdapter(tmp_path, registry)

    settings = store.load()

    assert settings.default_provider == "codex"
    assert settings.configuration_for("codex").enabled is True


def test_round_trips_driver_settings_without_credentials(
    tmp_path: Path,
) -> None:
    registry = default_driver_registry()
    store = DriverSettingsWorkspaceAdapter(tmp_path, registry)
    original = registry.default_settings()
    providers = tuple(
        DriverConfiguration(
            provider_id=item.provider_id,
            enabled=(item.provider_id in {"codex", "claude"}),
            executable=item.executable,
            credential_mode=item.credential_mode,
            credential_environment_variable=(
                item.credential_environment_variable
            ),
        )
        for item in original.providers
    )
    settings = DriverSettings(
        schema_version=1,
        default_provider="claude",
        providers=providers,
    )

    store.save(settings)
    loaded = store.load()
    raw = store.path.read_text(encoding="utf-8")

    assert loaded == settings
    assert "secret" not in raw.lower()
    assert "token" not in raw.lower()


def test_rejects_unknown_provider_configuration(tmp_path: Path) -> None:
    registry = default_driver_registry()
    store = DriverSettingsWorkspaceAdapter(tmp_path, registry)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_provider": "unknown",
                "providers": [
                    {
                        "provider_id": "unknown",
                        "enabled": True,
                        "executable": "unknown",
                        "credential_mode": "none",
                        "credential_environment_variable": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(KeyError, match="unknown driver provider"):
        store.load()
