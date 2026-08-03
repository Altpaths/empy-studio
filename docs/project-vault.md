# Project Vault

The Project Vault is the durable memory of a project. It prevents repeated discovery, repeated uploads, and loss of decisions between coding-agent sessions.

## Create a vault

Keep the Vault outside the public repository when it may contain private source code:

```bash
empy vault init \
  --project-root /path/to/project \
  --vault /path/to/empy-vaults/project-id \
  --project-id project-id \
  --name "Project Name"
```

The command creates:

```text
vault.json
baseline/manifest.json
baseline/source.zip
knowledge/PROJECT_IDENTITY.md
knowledge/DECISIONS.md
tickets/active.json
design/
artifacts/
releases/index.json
```

Common secret, cache, dependency, build, Git, and Vault directories are excluded from the source snapshot.

## Inspect a vault

```bash
empy vault status --vault /path/to/empy-vaults/project-id
```

## Security

A Project Vault can contain private source code and project history. Do not commit it to a public repository. Store it in a protected local or encrypted location.
