# Empy Studio 0.1.55 — Ownership-safe persistence fixes

This patch fixes a real ownership-contract failure found while adding a
persistent backend feature to a PHP project. A backend node may now own a
related SQL/schema/migration file only when the ticket actually requests
database or persistence changes. Unrelated database context remains read-only,
and the runtime still stops genuinely unowned edits.

The adaptive token economy and explicit OmniRoute paid opt-in from 0.1.54 are
unchanged. The fix is covered by the full regression suite and packaged app
acceptance.

## Previous release context

The project screen offers Direct and explicit OmniRoute routes, while the
planner uses one bounded economy coordinator for low/medium-risk tickets that
would otherwise pay several provider harness costs. Explicit specialist fan-out
remains available for high-risk work or tickets that request it.
The existing fresh-installation behavior and fixed economy policy remain.
See docs/omniroute.md for setup, gateway trust assumptions and bounded probes.
Run `scripts/benchmark_token_efficiency.py` to measure deterministic planning
overhead without calling a provider.
The accompanying acceptance report distinguishes mocked tests from real free
provider failures; no real cost reduction or successful free coding is claimed.
