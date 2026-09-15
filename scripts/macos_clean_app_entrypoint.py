"""PyInstaller entry point for the empty-workspace macOS trial app."""

from __future__ import annotations

import sys
from pathlib import Path

from empy_studio.verification_pipeline import run_static_web_check
from empy_studio.web_desktop import main

if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments == ["--empy-static-web-check"]:
        raise SystemExit(run_static_web_check(Path.cwd()))
    if "--help" not in arguments:
        arguments = ["--clean", *arguments]
    raise SystemExit(main(arguments))
