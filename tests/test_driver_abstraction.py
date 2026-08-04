from __future__ import annotations

from pathlib import Path

from empy_studio.core import (
    DriverCapabilities,
    DriverConfiguration,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverInspection,
    DriverSettings,
    DriverStatus,
)
from empy_studio.drivers import (
    BaseDriver,
    DriverDefinition,
    DriverManager,
    DriverRegistry,
    default_driver_registry,
)


class FakeDriver(BaseDriver):
    def __init__(
        self,
        provider_id: str,
        display_name: str,
        configuration: DriverConfiguration,
    ) -> None:
        self._provider_id = provider_id
        self._display_name = display_name
        self.configuration = configuration

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return self._display_name

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            planning=True,
            code_editing=True,
            verification=False,
            streaming=False,
            cancellation=False,
        )

    def status(self) -> DriverStatus:
        return "available"

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        del refresh
        inspection = DriverInspection(
            provider_id=self.provider_id,
            display_name=self.display_name,
            availability="available",
            implemented=True,
            enabled=self.configuration.enabled,
            executable=self.configuration.executable,
            version="test-1",
            authenticated=True,
            message="Fake driver is ready.",
        )
        inspection.validate()
        return inspection

    def execute(
        self,
        request: DriverExecutionRequest,
    ) -> DriverExecutionResult:
        request.validate()
        return DriverExecutionResult(
            status="completed",
            return_code=0,
            summary="Fake execution completed.",
        )


def test_default_registry_exposes_capability_matrix() -> None:
    registry = default_driver_registry()

    matrix = {
        item.provider_id: item
        for item in registry.capability_matrix()
    }

    assert set(matrix) == {"claude", "codex", "gemini"}
    assert matrix["codex"].implemented is True
    assert matrix["codex"].capabilities.code_editing is True
    assert matrix["claude"].implemented is False
    assert matrix["gemini"].implemented is False


def test_unimplemented_providers_report_unavailable_state(
    tmp_path: Path,
) -> None:
    registry = default_driver_registry()
    settings = registry.default_settings()
    manager = DriverManager(
        registry=registry,
        settings=settings,
        artifact_root=tmp_path,
    )

    claude = manager.driver("claude").inspect()
    gemini = manager.driver("gemini").inspect()

    assert claude.ready is False
    assert claude.availability == "disabled"
    assert gemini.ready is False
    assert gemini.availability == "disabled"


def test_driver_manager_can_swap_selected_provider(tmp_path: Path) -> None:
    configuration_a = DriverConfiguration(
        provider_id="provider-a",
        enabled=True,
        executable="provider-a",
        credential_mode="none",
    )
    configuration_b = DriverConfiguration(
        provider_id="provider-b",
        enabled=True,
        executable="provider-b",
        credential_mode="none",
    )

    def factory_a(
        configuration: DriverConfiguration,
        artifact_root: Path,
    ) -> BaseDriver:
        del artifact_root
        return FakeDriver("provider-a", "Provider A", configuration)

    def factory_b(
        configuration: DriverConfiguration,
        artifact_root: Path,
    ) -> BaseDriver:
        del artifact_root
        return FakeDriver("provider-b", "Provider B", configuration)

    capabilities = DriverCapabilities(
        planning=True,
        code_editing=True,
        verification=False,
        streaming=False,
        cancellation=False,
    )
    registry = DriverRegistry(
        (
            DriverDefinition(
                provider_id="provider-a",
                display_name="Provider A",
                description="First fake provider.",
                capabilities=capabilities,
                implemented=True,
                default_configuration=configuration_a,
                factory=factory_a,
            ),
            DriverDefinition(
                provider_id="provider-b",
                display_name="Provider B",
                description="Second fake provider.",
                capabilities=capabilities,
                implemented=True,
                default_configuration=configuration_b,
                factory=factory_b,
            ),
        )
    )
    settings_a = DriverSettings(
        schema_version=1,
        default_provider="provider-a",
        providers=(configuration_a, configuration_b),
    )
    manager = DriverManager(
        registry=registry,
        settings=settings_a,
        artifact_root=tmp_path,
    )

    assert manager.driver().provider_id == "provider-a"

    settings_b = DriverSettings(
        schema_version=1,
        default_provider="provider-b",
        providers=(configuration_a, configuration_b),
    )
    manager.replace_settings(settings_b)

    assert manager.driver().provider_id == "provider-b"


def test_core_source_does_not_import_provider_package() -> None:
    core_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "empy_studio"
        / "core"
    )

    for path in core_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "empy_studio.drivers" not in source
        assert "Codex" not in source
