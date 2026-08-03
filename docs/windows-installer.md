# Windows Installer

Ticket 7.4 generates a standalone PowerShell installer for Windows x86_64.

The installer validates 64-bit Windows and Python, downloads over HTTPS,
verifies SHA-256, creates an isolated virtual environment, installs without
cloning, writes a command wrapper, and persists installation state.

It does not modify Registry or PATH, require Administrator access, uninstall
software, resolve latest GitHub assets, or update website links.
