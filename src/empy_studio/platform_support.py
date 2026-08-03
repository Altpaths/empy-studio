from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Literal, cast

OperatingSystem = Literal["macos", "linux", "windows"]
Architecture = Literal["x86_64", "arm64"]
InstallerKind = Literal["shell", "powershell"]
DistributionTarget = Literal[
    "macos-arm64",
    "macos-x86_64",
    "linux-arm64",
    "linux-x86_64",
    "windows-x86_64",
]

_SUPPORTED_TARGETS: tuple[DistributionTarget, ...] = (
    "macos-arm64",
    "macos-x86_64",
    "linux-arm64",
    "linux-x86_64",
    "windows-x86_64",
)


@dataclass(frozen=True)
class PlatformSpec:
    operating_system: OperatingSystem
    architecture: Architecture
    target: DistributionTarget
    installer_kind: InstallerKind

    @property
    def executable_suffix(self) -> str:
        return ".ps1" if self.installer_kind == "powershell" else ".sh"


def supported_targets() -> tuple[DistributionTarget, ...]:
    return _SUPPORTED_TARGETS


def parse_target(value: str) -> PlatformSpec:
    normalized = value.strip().lower()
    if normalized not in _SUPPORTED_TARGETS:
        raise ValueError(f"Unsupported distribution target: {value!r}")

    target = normalized
    os_name, architecture = target.split("-", 1)
    operating_system = cast(OperatingSystem, os_name)
    parsed_architecture = cast(Architecture, architecture)

    return PlatformSpec(
        operating_system=operating_system,
        architecture=parsed_architecture,
        target=target,
        installer_kind=(
            "powershell" if operating_system == "windows" else "shell"
        ),
    )


def normalize_operating_system(value: str) -> OperatingSystem:
    aliases: dict[str, OperatingSystem] = {
        "darwin": "macos",
        "mac": "macos",
        "macos": "macos",
        "linux": "linux",
        "windows": "windows",
        "win32": "windows",
        "cygwin": "windows",
    }
    try:
        return aliases[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported operating system: {value!r}") from exc


def normalize_architecture(value: str) -> Architecture:
    aliases: dict[str, Architecture] = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    try:
        return aliases[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported architecture: {value!r}") from exc


def resolve_target(
    operating_system: str,
    architecture: str,
) -> PlatformSpec:
    normalized_os = normalize_operating_system(operating_system)
    normalized_architecture = normalize_architecture(architecture)
    return parse_target(f"{normalized_os}-{normalized_architecture}")


def detect_current_platform() -> PlatformSpec:
    return resolve_target(platform.system(), platform.machine())
