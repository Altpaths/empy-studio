# Project Vault

The Project Vault is the durable memory of a project. It prevents repeated discovery, repeated uploads, repeated investigation of the same confirmed failure, and loss of decisions between coding-agent sessions.

## Failure memory

Empy keeps a small, project-scoped failure ledger beside the workspace state. A failure is identified by a normalized fingerprint of its kind, confirmed cause, safe relative targets, and bounded evidence. Repeated observations of the same cause are coalesced instead of creating another record. The ledger survives application restarts and new tickets in the same project, while a different project cannot read its records.

Before a provider run, Empy checks this ledger. If the new ticket would repeat the same failure against the same unchanged target, the run is stopped locally and the UI shows the recorded cause and the next corrective action. A changed target, changed project snapshot, or a corrective request can proceed and is evaluated again. This is the token saving boundary: no model call is made for an unchanged known failure.

Records remain open until the real Verification gate passes. An Agent report alone cannot resolve a failure. A failed or incomplete verification never marks memory as fixed; a later observation can reopen a previously resolved record. Stored summaries, actions, paths, evidence, and ticket identifiers are bounded and redacted before persistence. Provider transcripts, credentials, arbitrary logs, and absolute local paths are not part of the durable UI memory. Detailed diagnostics remain behind the optional technical-details section for the current run.

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
