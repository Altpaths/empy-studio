from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from empy_studio.environment_preflight import (
    default_install_root,
    require_environment_ready,
    run_environment_preflight,
)
from empy_studio.platform_support import (
    PlatformSpec,
)


def platform_spec(
    operating_system: str = "macos",
) -> PlatformSpec:
    if operating_system == "windows":
        return PlatformSpec(
            operating_system="windows",
            architecture="x86_64",
            target="windows-x86_64",
            installer_kind="powershell",
        )

    return PlatformSpec(
        operating_system="macos",
        architecture="arm64",
        target="macos-arm64",
        installer_kind="shell",
    )


def test_ready_environment_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: True,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(),
    )

    assert result.status == "ready"
    assert result.is_ready is True
    assert result.to_dict()["failed_check_count"] == 0


def test_rejects_unsupported_python_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.sys.version_info",
        SimpleNamespace(
            major=3,
            minor=9,
            micro=0,
        ),
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: True,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(),
    )

    assert result.status == "blocked"
    assert any(
        check.name == "python_version"
        and check.status == "failed"
        for check in result.checks
    )


def test_rejects_unwritable_install_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: False,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(),
    )

    assert result.status == "blocked"
    assert any(
        check.name == "install_root"
        and check.status == "failed"
        for check in result.checks
    )


def test_unix_requires_curl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: True,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: (
            None
            if name == "curl"
            else f"/usr/bin/{name}"
        ),
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(),
    )

    assert any(
        check.name == "command_curl"
        and check.status == "failed"
        for check in result.checks
    )


def test_windows_does_not_require_curl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: True,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: None,
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(
            "windows"
        ),
    )

    curl_check = next(
        check
        for check in result.checks
        if check.name == "command_curl"
    )
    assert curl_check.status == "passed"
    assert curl_check.details["required"] is False


def test_default_install_root_for_unix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.Path.home",
        lambda: Path("/Users/test"),
    )

    result = default_install_root(
        platform_spec()
    )

    assert result == (
        Path("/Users/test")
        / ".local"
        / "share"
        / "empy-studio"
    )


def test_default_install_root_for_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LOCALAPPDATA",
        r"C:\Users\Test\AppData\Local",
    )

    result = default_install_root(
        platform_spec("windows")
    )

    assert result == (
        Path(r"C:\Users\Test\AppData\Local")
        / "EmpyStudio"
    )


def test_require_environment_ready_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.environment_preflight.os.access",
        lambda path, mode: False,
    )
    monkeypatch.setattr(
        "empy_studio.environment_preflight.shutil.which",
        lambda name: None,
    )

    result = run_environment_preflight(
        minimum_python="3.10",
        install_root=tmp_path / "install",
        platform_spec=platform_spec(),
    )

    with pytest.raises(
        RuntimeError,
        match="Environment preflight failed",
    ):
        require_environment_ready(result)
