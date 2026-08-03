# Clean Environment Rebuild

Ticket 8.2 verifies that Empy Studio can be installed and started from a clean,
isolated environment without relying on the developer's current virtual
environment.

## Pipeline

```text
Copy repository without local caches
  → Create a fresh virtual environment
  → Install the copied project with pip
  → Execute the installed CLI
  → Record commands, output, return codes, and project digest
```

## Isolation

The clean copy excludes:

- `.git`;
- `.venv`;
- Python bytecode;
- Ruff, MyPy, and Pytest caches;
- local build and distribution directories.

The current project and its active virtual environment are not modified.

## Evidence

The generated JSON evidence records:

- source directory;
- temporary workspace;
- clean virtual-environment path;
- Python executable;
- deterministic source digest;
- every executed command;
- stdout, stderr, and return code;
- overall `passed` or `failed` status.

This evidence will satisfy the `clean_environment` and support the
`clean_install` Release Candidate gates in later Ticket 8 steps.

## Scope boundary

Ticket 8.2 does not change versions, create release assets, publish a tag, or
contact GitHub.
