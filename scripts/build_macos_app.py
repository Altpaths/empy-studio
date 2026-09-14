#!/usr/bin/env python3
"""Build a self-contained, windowed macOS app with PyInstaller.

This command fails closed when PyInstaller is unavailable. It never labels a
shell launcher as a native app and never signs or notarizes on the user's
behalf; those steps remain explicit release gates.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def bundle_version(source_root: Path) -> str:
    """Use the version of the source being packaged, never an installed wheel."""
    document = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("macOS app builds require a numeric MAJOR.MINOR.PATCH project.version")
    return version


def write_app_spec(source_root: Path, work: Path, architecture: str, clean_workspace: bool) -> Path:
    """Set bundle metadata before PyInstaller creates its ad-hoc signature."""
    version = bundle_version(source_root)
    entrypoint = "macos_clean_app_entrypoint.py" if clean_workspace else "macos_app_entrypoint.py"
    spec = work / "Empy Studio.spec"
    spec.write_text(
        f"a = Analysis([{str(source_root / 'scripts' / entrypoint)!r}], "
        f"pathex=[{str(source_root / 'src')!r}], "
        f"datas=[({str(source_root / 'src/empy_studio/web')!r}, 'empy_studio/web')], "
        "hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[])\n"
        "pyz = PYZ(a.pure)\n"
        "exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Empy Studio', "
        "debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, "
        f"target_arch={None if architecture == 'auto' else architecture!r})\n"
        "coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Empy Studio')\n"
        "app = BUNDLE(coll, name='Empy Studio.app', bundle_identifier='com.altpaths.empystudio', "
        f"version={version!r}, info_plist={{'CFBundleShortVersionString': {version!r}, "
        f"'CFBundleVersion': {version!r}}})\n",
        encoding="utf-8",
    )
    return spec


def build_macos_app(
    *,
    source_root: Path,
    output: Path,
    architecture: str = "auto",
    clean_workspace: bool = False,
) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("macOS app bundles can only be built on macOS")
    source_root = source_root.expanduser().resolve()
    output = output.expanduser().resolve()
    if not (source_root / "src" / "empy_studio").is_dir():
        raise NotADirectoryError(source_root)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing app output: {output}")
    if architecture not in {"auto", "arm64", "x86_64", "universal2"}:
        raise ValueError(f"Unsupported macOS architecture: {architecture}")
    if shutil.which("pyinstaller") is None:
        try:
            import PyInstaller  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "PyInstaller is required for a self-contained macOS app build; "
                "install the release extra first"
            ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / f"{output.stem}-build"
    if work.exists():
        raise FileExistsError(f"Refusing to overwrite build directory: {work}")
    work.mkdir()
    spec = write_app_spec(source_root, work, architecture, clean_workspace)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(work / "dist"), "--workpath", str(work / "work"), str(spec),
    ]
    try:
        environment = os.environ.copy()
        environment["PYINSTALLER_CONFIG_DIR"] = str(work / "config")
        subprocess.run(command, cwd=source_root, check=True, env=environment)
        app = work / "dist" / "Empy Studio.app"
        if not app.is_dir():
            raise RuntimeError("PyInstaller completed without producing an .app bundle")
        with (app / "Contents" / "Info.plist").open("rb") as stream:
            metadata = plistlib.load(stream)
        version = bundle_version(source_root)
        if any(metadata.get(key) != version for key in ("CFBundleShortVersionString", "CFBundleVersion")):
            raise RuntimeError("Packaged app bundle version does not match project.version")
        shutil.move(str(app), output)
        xattr = shutil.which("xattr")
        if xattr is not None:
            subprocess.run([xattr, "-cr", str(output)], check=True)
        codesign = shutil.which("codesign")
        if codesign is not None:
            subprocess.run(
                [codesign, "--verify", "--deep", "--strict", str(output)],
                check=True,
            )
        return output
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--architecture",
        choices=("auto", "arm64", "x86_64", "universal2"),
        default="auto",
    )
    parser.add_argument(
        "--clean-workspace",
        action="store_true",
        help="Make the Finder app start a new empty workspace on every launch",
    )
    args = parser.parse_args(argv)
    app = build_macos_app(
        source_root=args.source_root,
        output=args.output,
        architecture=args.architecture,
        clean_workspace=args.clean_workspace,
    )
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
