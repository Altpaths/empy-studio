#!/usr/bin/env python3
"""Run a real Unix installer against a local wheel in an isolated HOME."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _replace_assignment(script: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    replacement = f"{name}={shlex.quote(value)}"
    updated, count = pattern.subn(replacement, script, count=1)
    if count != 1:
        raise ValueError(f"Installer does not contain exactly one {name} assignment")
    return updated


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
    if not installer.name.endswith(".sh"):
        raise ValueError("Unix installer smoke requires a .sh installer")
    package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    script = installer.read_text(encoding="utf-8")
    if f"TARGET={shlex.quote(target)}" not in script:
        raise ValueError(f"Installer target does not match requested target: {target}")
    script = _replace_assignment(script, "PACKAGE_URL", package.as_uri())
    script = _replace_assignment(script, "PACKAGE_SHA256", package_sha256)

    with tempfile.TemporaryDirectory(prefix="empy-installer-smoke-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        smoke_installer_path = root / installer.name
        smoke_installer_path.write_text(script, encoding="utf-8", newline="\n")
        smoke_installer_path.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        environment["TMPDIR"] = str(root / "tmp")
        environment["PATH"] = (
            f"{Path(sys.executable).parent}{os.pathsep}"
            f"{environment.get('PATH', '')}"
        )
        (root / "tmp").mkdir()
        result = subprocess.run(
            [str(smoke_installer_path)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Installer failed:\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        wrapper = home / ".local" / "bin" / "empy"
        state_path = home / ".local" / "share" / "empy-studio" / "install-state.json"
        if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
            raise RuntimeError("Installer did not create an executable empy wrapper")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("package_sha256") != package_sha256:
            raise RuntimeError("Installer state has the wrong package digest")
        wrapper_result = subprocess.run(
            [str(wrapper), "--help"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if wrapper_result.returncode != 0:
            raise RuntimeError(
                "Relocated wrapper failed:\n"
                f"stdout:\n{wrapper_result.stdout}\n"
                f"stderr:\n{wrapper_result.stderr}"
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
