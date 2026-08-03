# Transactional Plugin Installer

The installer converts one resolved and verified `.empy-plugin` artifact into
an installed, active plugin version without leaving partial state.

## Lifecycle

```text
created
  → resolving
  → verified
  → staged
  → committed
```

Any exception changes the transaction to `failed`.

## Guarantees

The installer:

- resolves local or remote sources through the Source Resolver;
- verifies package integrity and compatibility;
- extracts only approved package members;
- rejects traversal and unexpected archive entries;
- stages files before making them visible;
- atomically moves the staged version into the versioned Store;
- atomically updates Inventory;
- writes an Active Version pointer;
- records transaction state and evidence;
- removes staged and installed files after failed operations;
- restores the previous Inventory if activation fails;
- rejects installation of an already-installed version.

## Boundaries

This stage installs one new version and makes it active.

Upgrade policy, retaining previous active versions, explicit rollback, removal,
and CLI orchestration belong to later Ticket 4 stages.
