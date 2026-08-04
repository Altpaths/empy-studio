from __future__ import annotations

from abc import ABC, abstractmethod

from empy_studio.core import (
    DriverCapabilities,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverInspection,
    DriverStatus,
)


class BaseDriver(ABC):
    """Stable provider-independent base class for AI drivers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.provider_id

    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> DriverStatus:
        raise NotImplementedError

    @abstractmethod
    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        request: DriverExecutionRequest,
    ) -> DriverExecutionResult:
        raise NotImplementedError

    def cancel(self) -> None:
        """Cancel an active operation when supported."""
        raise NotImplementedError(
            f"{self.display_name} does not support cancellation"
        )
