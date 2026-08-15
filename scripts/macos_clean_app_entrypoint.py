"""PyInstaller entry point for the empty-workspace macOS trial app."""

from __future__ import annotations

import sys

from empy_studio.web_desktop import main

if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--help" not in arguments:
        arguments = ["--clean", *arguments]
    raise SystemExit(main(arguments))
