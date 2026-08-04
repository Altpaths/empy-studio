# Ticket 8 — Context Selector

## Goal

Build a visible, bounded context pack for every approved plan step without sending the entire project to an agent.

## Product flow

1. The user creates a task.
2. Empy generates and freezes an execution plan.
3. `Context Selector` scans project metadata with a hard candidate limit.
4. Sensitive paths, dependency directories, symlinks, binary files, and oversized files are excluded.
5. Remaining files receive deterministic relevance scores from task terms, approved likely paths, project markers, and the planned agent role.
6. Each plan step receives its own bounded context pack.
7. The Desktop UI exposes selected file paths, scores, reasons, hashes, truncation state, and included source content.

## Bounded defaults

- Maximum candidates scanned: 2,500
- Maximum files per context pack: 12
- Maximum bytes included per file: 32 KiB
- Maximum bytes per pack: 192 KiB
- Maximum candidate file size: 1 MiB

These are context-selection limits only. Token budgets and retry limits remain Ticket 9.

## Security rules

The selector never includes:

- `.env` and `.env.*`
- private-key and certificate files
- credential and secret files/directories
- `.git`, dependency, build, cache, or virtual-environment directories
- symlink targets
- binary files

Exclusions are visible in the Desktop Context Preview.

## Definition of Done

- The whole project is not sent: enforced by per-pack file and byte limits.
- Sensitive files are protected: enforced before any content read.
- Context is visible: file contents and selection evidence are displayed in the Desktop UI.
