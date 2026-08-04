# Workspace Persistence

## Status

Ticket 3 of `EMPY_PRODUCT_MASTER_PLAN.html`.

## Purpose

Empy Studio now has one local, versioned workspace for projects, tasks, runs,
and product settings. The desktop shell in the next phase can use this store
without inventing a second persistence layer.

## Storage

The default database is SQLite and uses only the Python standard library.

- macOS: `~/Library/Application Support/Empy Studio/workspace.sqlite3`
- Linux: `$XDG_DATA_HOME/Empy Studio/workspace.sqlite3`
- Windows: `%LOCALAPPDATA%/Empy Studio/workspace.sqlite3`
- Tests and controlled deployments may set `EMPY_WORKSPACE_PATH`.

## Stored records

- Projects and recent-open timestamps
- User-created and template-based tasks
- Run state and evidence location
- Product settings

## Schema policy

The database contains an explicit `schema_version`. Migrations are applied in
order. A database produced by a newer Empy build is rejected instead of being
silently damaged.

## Safety

- Foreign keys are enabled.
- Each operation runs in a transaction.
- Failed operations roll back.
- Removing a project cascades its tasks and runs.
- Project roots are normalized to absolute paths.

## Scope boundary

This ticket does not build the Desktop Shell, Project Picker, Task Composer,
Planner, AI execution, or visual run history. It only provides the persistent
foundation required by those roadmap tickets.
