from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .contracts import DriverCapabilities

DriverAvailability = Literal[
    "available",
    "missing",
    "unauthenticated",
    "unavailable",
    "disabled",
]
DriverCredentialMode = Literal[
    "cli_login",
    "environment",
    "none",
]


@dataclass(frozen=True)
class DriverInspection:
    provider_id: str
    display_name: str
    availability: DriverAvailability
    implemented: bool
    enabled: bool
    executable: str | None
    version: str | None
    authenticated: bool
    message: str
    remediation: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.implemented
            and self.enabled
            and self.availability == "available"
        )

    def validate(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        if not self.message.strip():
            raise ValueError("driver inspection message cannot be empty")
        if self.availability == "disabled" and self.enabled:
            raise ValueError("disabled inspection cannot be enabled")
        if self.ready and not self.executable:
            raise ValueError("ready driver requires an executable")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DriverConfiguration:
    provider_id: str
    enabled: bool
    executable: str | None
    credential_mode: DriverCredentialMode
    credential_environment_variable: str | None = None

    def validate(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        if self.executable is not None and not self.executable.strip():
            raise ValueError("executable cannot be blank")
        if (
            self.credential_mode == "environment"
            and not self.credential_environment_variable
        ):
            raise ValueError(
                "environment credential mode requires a variable name"
            )
        if (
            self.credential_mode != "environment"
            and self.credential_environment_variable is not None
        ):
            raise ValueError(
                "credential environment variable requires environment mode"
            )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DriverSettings:
    schema_version: int
    default_provider: str
    providers: tuple[DriverConfiguration, ...]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported driver settings schema")
        if not self.default_provider.strip():
            raise ValueError("default_provider cannot be empty")
        provider_ids: set[str] = set()
        for configuration in self.providers:
            configuration.validate()
            if configuration.provider_id in provider_ids:
                raise ValueError(
                    f"duplicate driver configuration: {configuration.provider_id}"
                )
            provider_ids.add(configuration.provider_id)
        if self.default_provider not in provider_ids:
            raise ValueError("default provider must have a configuration")
        default = self.configuration_for(self.default_provider)
        if not default.enabled:
            raise ValueError("default provider must be enabled")

    def configuration_for(self, provider_id: str) -> DriverConfiguration:
        for configuration in self.providers:
            if configuration.provider_id == provider_id:
                return configuration
        raise KeyError(provider_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_provider": self.default_provider,
            "providers": [item.to_dict() for item in self.providers],
        }


@dataclass(frozen=True)
class DriverCapabilityEntry:
    provider_id: str
    display_name: str
    implemented: bool
    capabilities: DriverCapabilities
    description: str

    def validate(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        if not self.description.strip():
            raise ValueError("driver capability description cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "implemented": self.implemented,
            "capabilities": self.capabilities.to_dict(),
            "description": self.description,
        }
