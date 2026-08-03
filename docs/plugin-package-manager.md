# Plugin Package Manager

The Package Manager extends the Plugin SDK lifecycle without changing its
contracts:

```text
Verified .empy-plugin
  → transactional package operation
  → versioned plugin store
  → active-version pointer
  → Plugin Discovery and Loader
```

## Plugin store

The store uses a platform-neutral structure:

```text
<store>/
  inventory.json
  .store.lock
  transactions/
  packages/
    <plugin-id>/
      <version>/
  active/
    <plugin-id>
```

`inventory.json` is the authoritative state. It records every installed
version, the active version, the package SHA-256, source, installation time,
and installed path.

## Consistency

Store mutations require an exclusive lock. Inventory writes use a temporary
file followed by atomic replacement.

Every install, upgrade, rollback, and removal operation creates a transaction
journal record. Later Package Manager stages update these records through
their lifecycle so interrupted operations can be diagnosed or recovered.

## Responsibility boundary

This module does not download, verify, extract, activate, or remove packages.
Those responsibilities are implemented in the next Ticket 4 stages.
