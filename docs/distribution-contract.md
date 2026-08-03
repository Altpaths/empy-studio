# Distribution Contract and Platform Matrix

Ticket 7.1 defines the stable contract used by the final installers and the
GitHub Release distribution layer.

## Supported v1 targets

```text
macos-arm64
macos-x86_64
linux-arm64
linux-x86_64
windows-x86_64
```

Windows ARM64 is intentionally outside the v1 distribution matrix.

## Installer types

- macOS and Linux use shell installers (`.sh`);
- Windows uses PowerShell (`.ps1`).

## Distribution manifest

The manifest binds product, version, GitHub Release tag, repository, minimum
Python version, installer assets, SHA-256, byte size, and media type.

## Scope boundary

Ticket 7.1 does not inspect Python, download assets, install Empy Studio,
modify PATH, uninstall software, call GitHub, or modify the website.
