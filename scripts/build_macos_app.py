#!/usr/bin/env python3
"""Build a self-contained, windowed macOS app with PyInstaller.

This command fails closed when PyInstaller is unavailable. It never labels a
shell launcher as a native app and never signs or notarizes on the user's
behalf; those steps remain explicit release gates.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def build_macos_app(
    *,
    source_root: Path,
    output: Path,
    architecture: str = "auto",
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
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "Empy Studio",
        "--osx-bundle-identifier",
        "com.altpaths.empystudio",
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work / "spec"),
        "--paths",
        str(source_root / "src"),
        "--add-data",
        f"{source_root / 'src' / 'empy_studio' / 'web'}:empy_studio/web",
    ]
    if architecture != "auto":
        command.extend(["--target-architecture", architecture])
    command.append(str(source_root / "scripts" / "macos_app_entrypoint.py"))
    try:
        environment = os.environ.copy()
        environment["PYINSTALLER_CONFIG_DIR"] = str(work / "config")
        subprocess.run(command, cwd=source_root, check=True, env=environment)
        app = work / "dist" / "Empy Studio.app"
        if not app.is_dir():
            raise RuntimeError("PyInstaller completed without producing an .app bundle")
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
    args = parser.parse_args(argv)
    app = build_macos_app(
        source_root=args.source_root,
        output=args.output,
        architecture=args.architecture,
    )
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
