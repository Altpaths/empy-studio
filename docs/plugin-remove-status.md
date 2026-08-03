# Plugin Removal, Listing, and Store Status

## Listing

The Package Manager inventory view reports:

- installed plugins;
- active version;
- all installed versions;
- package SHA-256;
- source;
- installation time;
- whether each installed path exists.

## Store status

Health inspection compares Inventory, Active Pointers, installed directories,
manifests, and payload directories.

A Store is `healthy` only when no structural inconsistency is found. Otherwise,
it is `degraded` and returns explicit issues.

## Version removal

An inactive version may be removed directly.

An active version may be removed only when:

- another installed version is supplied as `replacement_version`; or
- it is the last installed version, in which case the plugin is removed
  completely.

Removal uses a transaction journal and temporary trash location. Inventory and
the Active Pointer are restored if the operation fails.

## Complete removal

Complete plugin removal deletes every installed version through the same
transactional version-removal path and removes its Active Pointer and Inventory
entry.

CLI orchestration is added in Ticket 4.6.
