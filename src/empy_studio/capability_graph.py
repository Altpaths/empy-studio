from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    capability_id: str
    aliases: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    weight: float = 1.0
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        return cls(
            capability_id=str(data["capability_id"]),
            aliases=tuple(str(item) for item in data.get("aliases", [])),
            implies=tuple(str(item) for item in data.get("implies", [])),
            requires=tuple(str(item) for item in data.get("requires", [])),
            weight=max(0.0, float(data.get("weight", 1.0))),
            description=str(data.get("description", "")),
        )


class CapabilityGraph:
    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._aliases: dict[str, str] = {}
        for capability in capabilities or []:
            self.register(capability)
        self.validate()

    def register(self, capability: Capability) -> None:
        if capability.capability_id in self._capabilities:
            raise ValueError(f"Capability already registered: {capability.capability_id}")
        self._capabilities[capability.capability_id] = capability
        for alias in capability.aliases:
            if alias in self._aliases or alias in self._capabilities:
                raise ValueError(f"Capability alias already registered: {alias}")
            self._aliases[alias] = capability.capability_id

    def canonical(self, capability_id: str) -> str:
        return self._aliases.get(capability_id, capability_id)

    def get(self, capability_id: str) -> Capability:
        canonical = self.canonical(capability_id)
        try:
            return self._capabilities[canonical]
        except KeyError as exc:
            raise KeyError(f"Unknown capability: {capability_id}") from exc

    def expand(self, capability_ids: tuple[str, ...] | list[str]) -> set[str]:
        expanded: set[str] = set()
        pending = [self.canonical(item) for item in capability_ids]
        while pending:
            capability_id = pending.pop()
            if capability_id in expanded:
                continue
            capability = self.get(capability_id)
            expanded.add(capability_id)
            pending.extend(self.canonical(item) for item in capability.implies)
            pending.extend(self.canonical(item) for item in capability.requires)
        return expanded

    def weight(self, capability_id: str) -> float:
        return self.get(capability_id).weight

    def validate(self) -> None:
        for capability in self._capabilities.values():
            for related in (*capability.implies, *capability.requires):
                canonical = self.canonical(related)
                if canonical not in self._capabilities:
                    raise ValueError(
                        f"Capability {capability.capability_id} references unknown capability "
                        f"{related}"
                    )

        for capability_id in self._capabilities:
            self.expand((capability_id,))

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "capability_id": item.capability_id,
                "aliases": list(item.aliases),
                "implies": list(item.implies),
                "requires": list(item.requires),
                "weight": item.weight,
                "description": item.description,
            }
            for item in sorted(self._capabilities.values(), key=lambda item: item.capability_id)
        ]
