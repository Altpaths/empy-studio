from __future__ import annotations

from typing import Any

from empy_studio.plugin_manager_cli import (
    install_plugin_command,
    list_plugins_command,
    plugin_status_command,
    remove_plugin_command,
    rollback_plugin_command,
    upgrade_plugin_command,
)


def test_install_command_delegates(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_install(
        source: str,
        store_root: str,
        *,
        empy_version: str,
    ) -> dict[str, Any]:
        captured.update(
            {
                "source": source,
                "store_root": store_root,
                "empy_version": empy_version,
            }
        )
        return {"status": "installed"}

    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.install_plugin",
        fake_install,
    )

    result = install_plugin_command(
        "plugin.empy-plugin",
        "/store",
        "1.0.0",
    )

    assert result["status"] == "installed"
    assert captured["source"] == "plugin.empy-plugin"


def test_upgrade_command_delegates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.upgrade_plugin",
        lambda source, store_root, *, empy_version: {
            "status": "installed",
            "operation": "upgrade",
            "version": "2.0.0",
        },
    )

    result = upgrade_plugin_command(
        "plugin-2.empy-plugin",
        "/store",
        "1.0.0",
    )

    assert result["operation"] == "upgrade"


def test_rollback_command_delegates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.rollback_plugin",
        lambda plugin_id, version, store_root: {
            "status": "rolled_back",
            "plugin_id": plugin_id,
            "active_version": version,
        },
    )

    result = rollback_plugin_command(
        "example-plugin",
        "1.0.0",
        "/store",
    )

    assert result["active_version"] == "1.0.0"


def test_remove_complete_plugin_delegates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.remove_plugin",
        lambda plugin_id, store_root: {
            "status": "removed",
            "plugin_id": plugin_id,
        },
    )

    result = remove_plugin_command(
        "example-plugin",
        "/store",
    )

    assert result["plugin_id"] == "example-plugin"


def test_remove_version_delegates(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_remove_version(
        plugin_id: str,
        version: str,
        store_root: str,
        *,
        replacement_version: str | None,
    ) -> dict[str, Any]:
        captured.update(
            {
                "plugin_id": plugin_id,
                "version": version,
                "replacement_version": replacement_version,
            }
        )
        return {"status": "removed"}

    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.remove_plugin_version",
        fake_remove_version,
    )

    remove_plugin_command(
        "example-plugin",
        "/store",
        version="2.0.0",
        replacement_version="1.0.0",
    )

    assert captured["version"] == "2.0.0"
    assert captured["replacement_version"] == "1.0.0"


def test_list_and_status_commands_delegate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.list_plugins",
        lambda store_root: {
            "status": "ok",
            "store_root": store_root,
        },
    )
    monkeypatch.setattr(
        "empy_studio.plugin_manager_cli.plugin_store_status",
        lambda store_root: {
            "status": "healthy",
            "store_root": store_root,
        },
    )

    assert list_plugins_command("/store")["status"] == "ok"
    assert plugin_status_command("/store")["status"] == "healthy"
