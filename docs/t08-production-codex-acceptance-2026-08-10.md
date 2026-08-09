# Ticket 8 — Production Codex driver acceptance evidence

Date: 2026-08-10
Branch: `agent/t08-cli-compat-20260810`
Baseline: `141ea60`

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
- The adapter no longer emits the removed Codex `--ask-for-approval` option.
- Explicitly selected non-Git projects receive `--skip-git-repo-check`; Git
  projects retain the normal trust check.
- Targeted acceptance: 26 tests passed after the compatibility fix.
- Full suite: 527 tests passed in 6.85 seconds.
- Ruff: passed for `src` and `tests`.
- MyPy: `Success: no issues found in 115 source files`.
- Python `compileall`: passed.
- The normal macOS Terminal now reports `codex-cli 0.147.0`, successful
  authentication, and a clean `codex exec --help` check.
- A direct, ephemeral, read-only provider smoke returned
  `EMPY_T08_SMOKE_OK`; usage was 12,776 input and 11 output tokens.
- The real Empy adapter smoke completed against an isolated non-Git fixture,
  returned `EMPY_T08_ADAPTER_OK`, persisted 4 JSONL events, and exited with
  return code 0.

## RESOLVED

- The initial live acceptance exposed two real CLI compatibility failures:
  the legacy approval flag and missing non-Git trust-check bypass. Both were
  fixed in the isolated branch and revalidated with the real provider.

## ENVIRONMENT NOTE

- Running Codex from a more restricted nested sandbox can still produce a
  host state-database or PATH-helper permission error. Empy preserves that as
  a fail-closed `sandbox_error`; it does not disable the sandbox automatically.

## LIMITATION

- This smoke intentionally performs no project edit. A multi-node,
  write-enabled acceptance remains part of the separate real-project
  acceptance gate.
