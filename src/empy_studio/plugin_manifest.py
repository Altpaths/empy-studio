from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, cast

from .plugin_contracts import PluginHook

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?P<suffix>[a-zA-Z0-9.-]*)$"
)
REQUIREMENT_PATTERN = re.compile(
    r"^(?P<operator>>=|<=|==|>|<)?"
    r"(?P<version>\d+\.\d+\.\d+[a-zA-Z0-9.-]*)$"
)


def parse_version(value: str) -> tuple[int, int, int, str]:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Invalid semantic version: {value}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("suffix"),
    )


def is_compatible(current_version: str, requirement: str) -> bool:
    match = REQUIREMENT_PATTERN.fullmatch(requirement.strip())
    if match is None:
        raise ValueError(f"Invalid Empy version requirement: {requirement}")

    operator = match.group("operator") or "=="
    required = parse_version(match.group("version"))
    current = parse_version(current_version)

    current_core = current[:3]
    required_core = required[:3]

    if operator == "==":
        return current == required
    if operator == ">=":
        return current_core >= required_core
    if operator == "<=":
        return current_core <= required_core
    if operator == ">":
        return current_core > required_core
    if operator == "<":
        return current_core < required_core
    raise ValueError(f"Unsupported version operator: {operator}")


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    empy_requires: str
    entrypoint: str
    hooks: tuple[PluginHook, ...]
    description: str = ""
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        hooks_raw = tuple(
            str(item)
            for item in data.get("hooks", [])
        )
        allowed = {
            "agent",
            "adapter",
            "validator",
            "context_provider",
        }
        unknown = sorted(set(hooks_raw) - allowed)
        if unknown:
            raise ValueError(f"Unknown plugin hooks: {unknown}")

        hooks = tuple(
            cast(PluginHook, item)
            for item in hooks_raw
        )

        manifest = cls(
            plugin_id=str(data["plugin_id"]),
            name=str(data.get("name", data["plugin_id"])),
            version=str(data["version"]),
            empy_requires=str(data["empy_requires"]),
            entrypoint=str(data["entrypoint"]),
            hooks=hooks,
            description=str(data.get("description", "")),
            capabilities=tuple(
                str(item)
                for item in data.get("capabilities", [])
            ),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not self.plugin_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in self.plugin_id
        ):
            raise ValueError(
                "plugin_id must use lowercase letters, digits, '-' or '_'"
            )
        parse_version(self.version)
        if ":" not in self.entrypoint:
            raise ValueError(
                "entrypoint must use 'module.path:object_name' format"
            )
        module_name, object_name = self.entrypoint.split(":", 1)
        if not module_name or not object_name:
            raise ValueError(
                "entrypoint must use 'module.path:object_name' format"
            )
        is_compatible("1.0.0", self.empy_requires)

    def supports(self, empy_version: str) -> bool:
        return is_compatible(empy_version, self.empy_requires)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
