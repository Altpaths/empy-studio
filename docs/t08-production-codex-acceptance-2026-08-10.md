# Ticket 8 — Production Codex driver acceptance evidence

Date: 2026-08-10
Branch: `agent/t08-production-codex-20260810`
Baseline: `e53512c`

## FACT

- The implementation was performed in an isolated worktree. The canonical
  Empy baseline and the Holda fixture were not edited.
- The driver retains bounded `read-only`/`workspace-write` sandbox selection,
  explicit `danger-full-access` override behavior, JSONL event evidence,
  usage aggregation, timeout, cancellation, and Git/file-scope auditing.
- Preflight and Environment Doctor now detect known host PATH-alias,
  app-server, state-database, and sandbox initialization diagnostics without
  starting a model turn or reading credential files.
- Host readiness failures are persisted as an actionable `sandbox_error`; the
  runtime never silently downgrades a node to unrestricted access.
- Targeted acceptance: 27 tests passed.
- Full suite: 527 tests passed in 6.88 seconds.
- Ruff: passed for `src` and `tests`.
- MyPy: `Success: no issues found in 115 source files`.
- Python `compileall`: passed.
- A real local Codex preflight check found `codex-cli 0.146.0`, successful
  authentication, and the host diagnostic `path_aliases`.

## BLOCKED

- A real provider model turn was not run on this host. Codex emits
  `could not create PATH aliases: Operation not permitted` during local
  commands, so Empy correctly reports the environment as unavailable with
  `sandbox_error`. This is an external host-permission limitation, not a
  failed unit or fake-CLI acceptance test.

## INFERENCE

- The fake-CLI subprocess contract and the existing deterministic tests cover
  the driver event, usage, timeout, cancellation, and evidence paths without
  spending provider tokens. A live provider acceptance must still be repeated
  after the host Codex installation is repaired.

## UNKNOWN

- Whether the current Codex installation can complete a real model turn after
  its PATH-alias and local app-server permissions are repaired.
