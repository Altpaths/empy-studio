# Empy Studio 0.1.56 — Semantic scope routing and exact creation ownership

This patch fixes the live Holda failure where a Persian request for an asset
price chart was routed to an unrelated backend context and then stopped after
the provider edited `FinanceService.php` outside the node's approved ownership.
Persian market and chart terms now route both specialist roles, Project Brain
ranking selects the existing finance modules and interactive asset script, and
the graph grants one exact missing `asset-prices.php` endpoint target for a PHP
market ticket. Existing files still require exact ownership, and unrequested
new files such as migrations still fail the scope audit.

The fix is covered by the full regression suite, static checks, and a runtime
test that allows the exact endpoint while rejecting an unplanned migration.

## v0.1.55 context

This patch fixes a real ownership-contract failure found while adding a
persistent backend feature to a PHP project. A backend node may now own a
related SQL/schema/migration file only when the ticket actually requests
database or persistence changes. Unrelated database context remains read-only,
and the runtime still stops genuinely unowned edits.

The adaptive token economy and explicit OmniRoute paid opt-in from 0.1.54 are
unchanged. The fix is covered by the full regression suite and packaged app
acceptance.

## Product context

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
