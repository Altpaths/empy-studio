# Consolidated Product Checkpoint — Through Ticket 11

## Master Plan position

- Phase 1: complete
- Phase 2: complete
- Phase 3, Tickets 7–10: complete
- Phase 4, Ticket 11: complete
- Next: Ticket 12 — Driver Abstraction and Settings

## Ticket 11 result

Empy can now execute a ready Agent Run Graph through the locally installed Codex
CLI. The desktop performs installation and authentication preflight, starts the
run outside Tk's main thread, streams structured progress, supports cancellation
and timeout, preserves session evidence, and exposes completed runs from the
Runs page.

Every execution remains bound to the approved plan, Context Selector output,
locked Token Budget, Dispatcher ownership, and dependency waves. Git projects
must start clean, and every completed node is audited for unowned file changes
or forbidden Git-history changes.

## Scope boundary

Ticket 11 contains one production provider: Codex. Provider-neutral settings,
provider selection, and additional production drivers remain Ticket 12. Patch
synchronization and conflict resolution are not included.

## Validation

- Production driver, graph runtime, persistence, and desktop contract tests are
  included.
- One test exercises the real subprocess contract through a fake executable,
  rather than replacing `subprocess.Popen`.
- Full repository tests and Python compilation pass in the build environment.
- The installation helper runs Ruff, strict mypy, pytest, and compileall against
  the user's actual repository before a commit is created.
