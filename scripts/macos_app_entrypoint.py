"""PyInstaller entry point for the Finder-launchable Empy Studio app."""

from empy_studio.web_desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
