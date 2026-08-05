# Ticket 15 — Diff Review, Accept & Revert

Ticket 15 gives the user final, explicit control over workspace changes before delivery.

## Review Workspace

- Captures the current Git `HEAD` and every changed, deleted, renamed, staged, or untracked file.
- Shows a readable unified diff for text files and an explicit marker for binary additions.
- Lists each file with its change kind and decision state.
- Persists Review Reports under the Empy workspace.

## Accept

Accept records an explicit user decision and keeps the current working-tree content unchanged. It does not stage, commit, push, merge, or release anything.

## Revert

Revert restores tracked files from the captured repository baseline and removes explicitly reverted untracked additions. Before changing the workspace, Empy verifies that:

- repository `HEAD` still matches the captured revision;
- the selected file has not changed since the diff was captured;
- a renamed file's original path has not reappeared.

These checks prevent a stale review decision from destroying newer work.

## Commit boundary

Review Workspace never creates a Git commit. Commit and push remain separate actions requiring explicit user authorization outside this workspace.
