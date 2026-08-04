# Sync & Conflict Resolver

Ticket 13 adds the provider-neutral synchronization boundary between agent
execution and verification. Agent outputs enter a deterministic patch queue;
they do not write directly through this subsystem without ownership and base
state checks.

## Contract

Each `AgentPatch` records the run node, agent, plan step, relative path,
operation, expected base SHA-256, content, and local sequence. The resolver
orders patches by Agent Run Graph sequence and then patch sequence.

Before apply, the resolver checks:

- the patch identity matches an existing run node;
- the node owns the target file in the approved Agent Run Graph;
- the file is not in protected exclusions;
- create, modify, or delete matches the current file state;
- the current SHA-256 matches the patch base;
- no other queued agent patch targets the same path.

## Conflict policy

Conflicts are never silently discarded or automatically merged. A blocked Sync
Report preserves every patch and exposes one or more conflict records. The user
must choose one of:

- `apply-patch`: intentionally apply the agent content despite the conflict;
- `keep-current`: skip the patch and preserve the workspace file;
- `manual-content`: write user-supplied merged content.

Any unresolved conflict blocks apply. Duplicate writes remain visible as
separate queue entries so neither agent result is lost.

## Safe apply

All unchanged bases are revalidated immediately before the first write. File
replacement uses a temporary file and `os.replace`. If any operation fails,
previous file bytes are restored for every target already touched by the sync.
No Git commit is created.

## Desktop persistence

`SyncWorkspaceAdapter` stores versioned Sync Reports under
`sync-reports/<sync-id>.json`. This is the data contract for the conflict UI and
for the later Diff Review, Accept, and Revert workflow.
