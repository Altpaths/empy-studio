# macOS and Linux Installer

Ticket 7.3 generates standalone shell installers for supported macOS and
Linux targets.

## Supported targets

```text
macos-arm64
macos-x86_64
linux-arm64
linux-x86_64
```

## Installation flow

```text
Detect OS and architecture
  → Locate supported Python
  → Download wheel or ZIP from HTTPS
  → Verify SHA-256
  → Create isolated virtual environment
  → Install package with pip
  → Atomically publish version directory
  → Update current-version link
  → Create ~/.local/bin/empy, empy-web, and empy-desktop wrappers
  → Persist install-state.json
```

The installer does not clone the repository, use sudo, or modify shell
profiles. Windows, uninstall, and latest-release resolution remain in later
Ticket 7 sections.
