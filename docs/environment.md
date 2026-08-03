# Environment Doctor, Bootstrap, and Validation

Empy Studio includes three commands that reduce setup friction and prevent avoidable CI failures.

## Diagnose the environment

```bash
empy doctor --project-root .
```

The report checks Python compatibility, virtual-environment state, Git, GitHub CLI, GitHub authentication, repository metadata, CI configuration, and an optional Project Vault.

```bash
empy doctor --project-root . --vault .empy/vault
```

A check is never reported as passed unless it was actually observed.

## Bootstrap a local installation

Preview the commands without changing the machine:

```bash
empy bootstrap --project-root . --dev --dry-run
```

Create `.venv`, upgrade pip, and install the project:

```bash
empy bootstrap --project-root . --dev
```

Empy Studio selects a compatible Python interpreter (3.10 or newer). The command returns the exact activation path instead of assuming that shell activation worked.

## Validate before push or release

```bash
empy validate
```

This runs Ruff, MyPy, and Pytest with the current interpreter. To apply safe Ruff fixes first:

```bash
empy validate --fix
```

Validation stops at the first failed gate and preserves the command output as evidence.
