# Plugin Upgrade and Rollback

Upgrade and rollback operate on the versioned Plugin Store created in Ticket
4.1.

## Upgrade

An upgrade installs a new verified version through the Transactional Installer
and makes it active.

Previous versions remain installed and addressable. The result reports:

- previous active version;
- newly active version;
- complete installed-version set;
- retained previous versions.

## Rollback

Rollback never downloads or reinstalls a package. It switches the active
version to one already present in the Store.

The operation:

- verifies the plugin exists;
- verifies the target version is installed;
- verifies the installed path still exists;
- updates Inventory atomically;
- updates the active pointer;
- records the previous and new active versions;
- restores Inventory and the pointer if activation fails.

## Boundary

Removal, inventory listing, health status, and CLI orchestration belong to the
next Ticket 4 stages.
