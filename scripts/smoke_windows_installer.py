#!/usr/bin/env python3
"""Run the Windows installer against a local wheel in an isolated profile.

The smoke test is intended to run on a real Windows GitHub Actions runner. It
rewrites only the package URL and digest in a temporary copy of the generated
installer, then validates the relocated installation and its command wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _replace_assignment(script: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^\${re.escape(name)}\s*=.*$", re.MULTILINE)
    replacement = f"${name} = {_powershell_quote(value)}"
    # A Windows path contains backslashes. Passing the replacement as a raw
    # string makes ``re`` interpret sequences such as ``\e`` as replacement
    # escapes, so return it through a callable instead.
    updated, count = pattern.subn(lambda _match: replacement, script, count=1)
    if count != 1:
        raise ValueError(
            f"Installer does not contain exactly one ${name} assignment"
        )
    return updated


def _find_powershell() -> str:
    for candidate in ("powershell.exe", "pwsh", "powershell"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("PowerShell was not found on the Windows runner")


def smoke_installer(
    *,
    installer: Path,
    package: Path,
    target: str,
) -> dict[str, str]:
    installer = installer.expanduser().resolve()
    package = package.expanduser().resolve()
    if not installer.is_file() or not package.is_file():
        raise FileNotFoundError(installer if not installer.is_file() else package)
    if not installer.name.endswith(".ps1"):
        raise ValueError("Windows installer smoke requires a .ps1 installer")
    if target != "windows-x86_64":
        raise ValueError("Windows installer smoke only supports windows-x86_64")

    package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    script = installer.read_text(encoding="utf-8-sig")
    if "$Target = 'windows-x86_64'" not in script:
        raise ValueError("Installer target does not match windows-x86_64")
    version_match = re.search(
        r"^\$Version\s*=\s*'([^']+)'$", script, re.MULTILINE
    )
    if version_match is None:
        raise ValueError("Installer does not contain a release version")
    version = version_match.group(1)
    # The generated installer intentionally supports file:// for isolated
    # smoke tests. A Windows path after file:// is consumed by its local-copy
    # branch without involving the network or a GitHub release.
    script = _replace_assignment(
        script,
        "PackageUrl",
        f"file://{package}",
    )
    script = _replace_assignment(script, "PackageSha256", package_sha256)

    with tempfile.TemporaryDirectory(prefix="empy-windows-installer-smoke-") as temporary:
        root = Path(temporary)
        local_app_data = root / "localappdata"
        temp_path = root / "temp"
        local_app_data.mkdir()
        temp_path.mkdir()
        smoke_installer_path = root / installer.name
        smoke_installer_path.write_text(script, encoding="utf-8-sig")

        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(local_app_data)
        environment["TEMP"] = str(temp_path)
        environment["TMP"] = str(temp_path)

        powershell = _find_powershell()
        command = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(smoke_installer_path),
        ]
        result = subprocess.run(
            command,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Windows installer failed:\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        install_root = local_app_data / "EmpyStudio"
        wrapper = local_app_data / "Microsoft" / "WindowsApps" / "empy.cmd"
        state_path = install_root / "install-state.json"
        current_path = install_root / "current.json"
        version_root = install_root / "versions" / version
        public_wrappers = {
            "empy": wrapper,
            "empy-web": local_app_data / "Microsoft" / "WindowsApps" / "empy-web.cmd",
            "empy-desktop": local_app_data / "Microsoft" / "WindowsApps" / "empy-desktop.cmd",
        }
        for command_name, public_wrapper in public_wrappers.items():
            if not public_wrapper.is_file():
                raise RuntimeError(
                    f"Installer did not create the {command_name}.cmd wrapper"
                )
        if not state_path.is_file() or not current_path.is_file():
            raise RuntimeError("Installer did not create installation state")

        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        current = json.loads(current_path.read_text(encoding="utf-8-sig"))
        if state.get("package_sha256") != package_sha256:
            raise RuntimeError("Installer state has the wrong package digest")
        if state.get("target") != target or state.get("version") != version:
            raise RuntimeError("Installer state has the wrong target or version")
        if current.get("version") != version:
            raise RuntimeError("Installer current pointer has the wrong version")
        if not (version_root / "venv" / "Scripts" / "python.exe").is_file():
            raise RuntimeError("Installer did not create the relocated venv")

        wrapper_command = subprocess.list2cmdline(
            [str(wrapper), "plan", "--help"]
        )
        wrapper_result = subprocess.run(
            wrapper_command,
            shell=True,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if wrapper_result.returncode != 0:
            raise RuntimeError(
                "Relocated Windows wrapper failed:\n"
                f"stdout:\n{wrapper_result.stdout}\n"
                f"stderr:\n{wrapper_result.stderr}"
            )

        web_wrapper_command = subprocess.list2cmdline(
            [str(public_wrappers["empy-web"]), "--help"]
        )
        web_wrapper_result = subprocess.run(
            web_wrapper_command,
            shell=True,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if web_wrapper_result.returncode != 0:
            raise RuntimeError(
                "Relocated Windows empy-web wrapper failed:\n"
                f"stdout:\n{web_wrapper_result.stdout}\n"
                f"stderr:\n{web_wrapper_result.stderr}"
            )

        return {
            "target": target,
            "version": str(state.get("version", "")),
            "wrapper": str(wrapper),
            "status": "passed",
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            smoke_installer(
                installer=args.installer,
                package=args.package,
                target=args.target,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
