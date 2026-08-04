from __future__ import annotations

from abc import ABC, abstractmethod

from empy_studio.core import (
    DriverCapabilities,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverStatus,
)


class BaseDriver(ABC):
    """Stable base class for provider-specific AI drivers."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> DriverStatus:
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
            f"{self.name} does not support cancellation"
        )
