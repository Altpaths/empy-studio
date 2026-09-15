"""PyInstaller entry point for the Finder-launchable Empy Studio app."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from empy_studio.platform_support import default_workspace_root
from empy_studio.web_desktop import main as desktop_main
from empy_studio.verification_pipeline import run_static_web_check


def installation_workspace(executable: Path | None = None) -> Path:
    """Keep data per extracted executable, without writing into the signed app.

    Filesystem identity survives relaunches and renames on the same volume.
    Re-extraction, copying across volumes, or replacing the executable creates a
    new workspace; the previous workspace remains available on disk. macOS birth
    time protects against inode reuse. The mtime fallback is for other platforms.
    """
    executable = executable if executable is not None else Path(sys.executable)
    identity = executable.stat()
    birth = getattr(identity, "st_birthtime_ns", None)
    if birth is None:
        birth = getattr(identity, "st_birthtime", identity.st_mtime_ns)
    key = f"{identity.st_dev}:{identity.st_ino}:{birth}"
    install_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return default_workspace_root() / "installations" / install_id


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--empy-static-web-check"]:
        return run_static_web_check(Path.cwd())
    if not any(arg == "--clean" or arg == "--workspace" or arg.startswith("--workspace=") for arg in args):
        args = ["--workspace", str(installation_workspace()), "--start-page", *args]
    return desktop_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
