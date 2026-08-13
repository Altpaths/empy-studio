# Ticket 16 Security Acceptance — 2026-08-10

## Scope

- Base commit: `a029a8e` (Ticket 8 compatibility fix already integrated on
  canonical `main`).
- Branch: `agent/t16-security-20260810`.
- Worktree: isolated from canonical `main` and the repository sample fixture.
- No GitHub push, release, or change to the canonical `main` checkout was
  performed by this ticket.

## Implemented controls

- Added `empy security audit` with project root, evidence path, Python
  executable, and source-directory controls.
- Persisted validated audit evidence and returned a non-zero CLI exit status
  for blocking findings or `pip check` failure.
- Redacted secret-like command output and credentials embedded in dependency
  URLs before evidence persistence.
- Skipped symlinked files in digest, secret, and Python-source scans.
- Rejected symlinks in every component of the configured source-directory path
  before scanning or resolving it.
- Retained the existing explicit Codex sandbox policy, plugin integrity checks,
  archive traversal/symlink checks, and installer verification gates.

## Verification

- Focused security/CLI tests: **14 passed**.
- Full suite: **532 passed**.
- Ruff: **passed**.
- MyPy: **passed** (`116` source files).
- Python compileall: **passed**.
- `git diff --check`: **passed**.
- Real CLI positive fixture: evidence and summary written, `status=passed`,
  exit code `0`.
- Real CLI negative run: evidence and summary written, `status=failed`, exit
  code `1`; the known fixture secret was absent from the evidence file.

Ticket 17 remains the next product ticket: real-project, non-developer
acceptance across sequential tickets, reopen/review/revert, new-project flow,
and export without terminal commands.
