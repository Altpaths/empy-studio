# Environment and Python Preflight

Ticket 7.2 validates a machine before any installer downloads or writes files.

## Checks

The preflight verifies:

- supported platform and architecture;
- minimum Python version;
- executable Python path;
- `venv` module;
- `pip` module;
- writable install-root parent;
- writable temporary directory;
- non-empty PATH;
- `curl` on macOS and Linux;
- optional PowerShell discovery.

## Default install roots

```text
macOS/Linux:
~/.local/share/empy-studio

Windows:
%LOCALAPPDATA%\EmpyStudio
```

## Result

The preflight returns a structured result with individual checks and an overall
`ready` or `blocked` status.

## Scope boundary

Ticket 7.2 does not download files, create environments, install packages,
change PATH, or modify the operating system.
