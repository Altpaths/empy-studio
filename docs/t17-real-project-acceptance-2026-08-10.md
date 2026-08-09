# Ticket 17 — Real-project acceptance evidence

Date: 2026-08-10
Branch: `agent/t17-real-acceptance-20260810`
Baseline: `1e42d0d` (`Implement Ticket 16 security hardening`)

## Scope

Ticket 17 validates the product path through Empy Studio itself. The Holda source directory is a read-only witness. Empy imports it into a separate workspace copy; all plan, agent, review, verification, and export operations target that imported copy.

## Implemented corrections

- The Web Desktop now exposes an authenticated `Stop run` action in Persian and English.
- Provider cancellation now covers the short interval before the worker enters the graph runtime.
- Verification commands run with a bounded polling loop, process-group termination, cancellation, and timeout cleanup. A blocked test command cannot leave the UI in `running` indefinitely.
- Terminal Codex, Verification, and Review evidence is persisted and linked to the workspace run. Reopening a ticket restores the run result, node statuses, verification report, and review decisions.
- Skipped graph nodes retain `skipped` status instead of being displayed as failed.
- Reset is rejected while a run is active so a user cannot discard the active cancellation handle.

## Acceptance evidence

The deterministic PHP scenario passed:

1. Import a PHP project through Empy into an isolated copy.
2. Build a bounded plan and run the provider-neutral local token benchmark.
3. Execute the first ticket, inspect the change, revert it, and export a verified single-root ZIP.
4. Reopen the workspace and confirm run, verification, review, and export evidence are available.
5. Add a second ticket, execute it, accept the change, and export a second verified ZIP.
6. Import a second project and confirm its project/task history is separate.
7. Compare the source witness digest before and after the full flow.

The same test was run with the Holda witness at:

`/Users/azadehsharifi/Documents/Codex/2026-08-09/lk/work/empy-holda-acceptance/holda-fixture`

Result: passed. The original Holda witness was not edited.

The live local UI smoke also passed: start a real Codex graph, click `توقف اجرا`, and observe the terminal `اجرا لغو شد` state without leaving the page in `running`.

## Validation commands

```text
pytest -q                         538 passed, 1 skipped
ruff check src tests              passed
mypy src                          Success: no issues found in 116 source files
python -m compileall -q src tests passed
```

The one skipped test is the optional real Holda witness test when `EMPY_HOLDA_FIXTURE` is not supplied; it was explicitly executed and passed in this acceptance run.

## Boundary

No changes were made to the Holda witness. No `.empy/` orchestration state is part of the intended product commit. This branch has not been merged into `main` and has not been pushed by this run.
