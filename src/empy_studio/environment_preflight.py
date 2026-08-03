from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .platform_support import (
    PlatformSpec,
    detect_current_platform,
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str
    details: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentPreflightResult:
    status: str
    platform: PlatformSpec
    python_executable: str
    python_version: str
    install_root: str
    checks: tuple[PreflightCheck, ...]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "platform": {
                "operating_system": (
                    self.platform.operating_system
                ),
                "architecture": self.platform.architecture,
                "target": self.platform.target,
                "installer_kind": (
                    self.platform.installer_kind
                ),
            },
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "install_root": self.install_root,
            "check_count": len(self.checks),
            "failed_check_count": sum(
                not check.passed
                for check in self.checks
            ),
            "checks": [
                check.to_dict()
                for check in self.checks
            ],
        }


def _version_tuple(value: str) -> tuple[int, int]:
    parts = value.strip().split(".")

    if (
        len(parts) != 2
        or not all(part.isdigit() for part in parts)
    ):
        raise ValueError(
            "Python version must use MAJOR.MINOR format"
        )

    return int(parts[0]), int(parts[1])


def _check_python_version(
    minimum_python: str,
) -> PreflightCheck:
    required = _version_tuple(minimum_python)
    current = (
        sys.version_info.major,
        sys.version_info.minor,
    )
    passed = current >= required

    return PreflightCheck(
        name="python_version",
        status="passed" if passed else "failed",
        message=(
            f"Python {current[0]}.{current[1]} "
            f"{'meets' if passed else 'does not meet'} "
            f"minimum {minimum_python}"
        ),
        details={
            "current": f"{current[0]}.{current[1]}",
            "minimum": minimum_python,
        },
    )


def _check_python_executable() -> PreflightCheck:
    executable = Path(sys.executable)

    passed = (
        executable.is_file()
        and os.access(executable, os.X_OK)
    )

    return PreflightCheck(
        name="python_executable",
        status="passed" if passed else "failed",
        message=(
            "Python executable is available"
            if passed
            else "Python executable is unavailable"
        ),
        details={
            "path": str(executable),
        },
    )


def _check_venv_module() -> PreflightCheck:
    try:
        import venv  # noqa: F401
    except ImportError:
        passed = False
    else:
        passed = True

    return PreflightCheck(
        name="venv_module",
        status="passed" if passed else "failed",
        message=(
            "Python venv module is available"
            if passed
            else "Python venv module is unavailable"
        ),
        details={},
    )


def _check_pip() -> PreflightCheck:
    try:
        import pip  # noqa: F401
    except ImportError:
        passed = False
    else:
        passed = True

    return PreflightCheck(
        name="pip_module",
        status="passed" if passed else "failed",
        message=(
            "pip is available"
            if passed
            else "pip is unavailable"
        ),
        details={},
    )


def _check_command(
    name: str,
    *,
    required: bool,
) -> PreflightCheck:
    resolved = shutil.which(name)
    passed = resolved is not None or not required

    return PreflightCheck(
        name=f"command_{name}",
        status="passed" if passed else "failed",
        message=(
            f"{name} is available"
            if resolved is not None
            else (
                f"{name} is optional"
                if not required
                else f"{name} is required but unavailable"
            )
        ),
        details={
            "required": required,
            "path": resolved,
        },
    )


def _check_install_root(
    install_root: Path,
) -> PreflightCheck:
    existing_parent = install_root

    while not existing_parent.exists():
        parent = existing_parent.parent
        if parent == existing_parent:
            break
        existing_parent = parent

    if not existing_parent.is_dir():
        return PreflightCheck(
            name="install_root",
            status="failed",
            message=(
                "No existing parent directory was found "
                "for the install root"
            ),
            details={
                "install_root": str(install_root),
                "existing_parent": str(existing_parent),
            },
        )

    writable = os.access(
        existing_parent,
        os.W_OK,
    )

    return PreflightCheck(
        name="install_root",
        status="passed" if writable else "failed",
        message=(
            "Install root parent is writable"
            if writable
            else "Install root parent is not writable"
        ),
        details={
            "install_root": str(install_root),
            "existing_parent": str(existing_parent),
        },
    )


def _check_temporary_directory() -> PreflightCheck:
    temporary_root = Path(
        tempfile.gettempdir()
    ).expanduser().resolve()

    passed = (
        temporary_root.is_dir()
        and os.access(temporary_root, os.W_OK)
    )

    return PreflightCheck(
        name="temporary_directory",
        status="passed" if passed else "failed",
        message=(
            "Temporary directory is writable"
            if passed
            else "Temporary directory is not writable"
        ),
        details={
            "path": str(temporary_root),
        },
    )


def _check_path_environment(
    platform_spec: PlatformSpec,
) -> PreflightCheck:
    path_value = os.environ.get("PATH", "")
    entries = [
        item
        for item in path_value.split(os.pathsep)
        if item
    ]

    passed = bool(entries)

    return PreflightCheck(
        name="path_environment",
        status="passed" if passed else "failed",
        message=(
            "PATH is configured"
            if passed
            else "PATH is empty"
        ),
        details={
            "entry_count": len(entries),
            "target": platform_spec.target,
        },
    )


def default_install_root(
    platform_spec: PlatformSpec,
) -> Path:
    home = Path.home()

    if platform_spec.operating_system == "windows":
        local_app_data = os.environ.get(
            "LOCALAPPDATA"
        )
        if local_app_data:
            return (
                Path(local_app_data)
                / "EmpyStudio"
            )
        return home / "AppData" / "Local" / "EmpyStudio"

    return home / ".local" / "share" / "empy-studio"


def run_environment_preflight(
    *,
    minimum_python: str,
    install_root: str | Path | None = None,
    platform_spec: PlatformSpec | None = None,
) -> EnvironmentPreflightResult:
    resolved_platform = (
        platform_spec
        if platform_spec is not None
        else detect_current_platform()
    )

    resolved_install_root = (
        Path(install_root).expanduser().resolve()
        if install_root is not None
        else default_install_root(
            resolved_platform
        ).expanduser().resolve()
    )

    checks = (
        _check_python_version(minimum_python),
        _check_python_executable(),
        _check_venv_module(),
        _check_pip(),
        _check_install_root(
            resolved_install_root
        ),
        _check_temporary_directory(),
        _check_path_environment(
            resolved_platform
        ),
        _check_command(
            "curl",
            required=(
                resolved_platform.operating_system
                != "windows"
            ),
        ),
        _check_command(
            "powershell",
            required=False,
        ),
    )

    ready = all(check.passed for check in checks)

    return EnvironmentPreflightResult(
        status="ready" if ready else "blocked",
        platform=resolved_platform,
        python_executable=sys.executable,
        python_version=(
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        install_root=str(
            resolved_install_root
        ),
        checks=checks,
    )


def require_environment_ready(
    result: EnvironmentPreflightResult,
) -> None:
    if result.is_ready:
        return

    failed = [
        check.name
        for check in result.checks
        if not check.passed
    ]
    raise RuntimeError(
        "Environment preflight failed: "
        + ", ".join(failed)
    )
