# Empy Studio 0.1.63 — shared token ledger and safe provider routing

Empy now accounts for the whole task with one shared ledger. Each graph node
reserves its locked allocation before a provider call; a reported provider
usage settles that reservation, while missing or estimated usage consumes the
full reservation. A fallback attempt receives only the unused part of the same
node allocation, so route switching cannot silently double the approved token
cap.

The run creates one immutable context manifest. Later writing specialists get
hashes and bounded handoff evidence for read-only files instead of receiving
the same source excerpts again. The manifest, ledger entries, prompt estimates,
and route attempts survive restart and are shown in the final report.

Fallbacks are explicit and bounded. They currently cover Codex-compatible
models configured through the local OmniRoute connection. Empy switches only
after a reported transient failure with no provider-reported or independently
audited worktree mutation. Authentication, quota, budget, policy, partial
mutation, and unknown-usage failures stop for verification or repair; paid
routes remain opt-in and are never selected automatically.

The full regression suite, strict lint, strict type checking, bytecode check,
and JavaScript syntax check pass. No provider call is made by the tests.

## Previous release context

# Empy Studio 0.1.62 — hard budget enforcement with verified recovery

Empy no longer treats a provider completion allowance as a successful node.
Every provider-reported fresh-token overage stays an explicit
`budget_exceeded` result and is shown in the run evidence. If the provider has
already emitted its terminal event and materialized a change inside the
approved ownership scope, Empy preserves that exact change for deterministic
Verification without paying for a blind retry. The change is promoted only
after all applicable checks pass; a failed check keeps the run failed and feeds
only that finding into the bounded repair workflow. A non-terminal overage, or
any unexpected follow-up turn after a terminal overage, is interrupted
immediately.

The reproduced ۳۰٬۳۸۶/۳۰٬۱۱۶ usage shape now remains budget-limited instead of
being accepted by a grace window. Regression, full-suite, and packaged
acceptance checks cover both the hard stop and the verified recovery path. No
provider call is made by the test suite.

## Previous release context

# Empy Studio 0.1.61 — packaged Verification entrypoint

The packaged macOS app now runs Empy’s built-in Static HTML/CSS/JS check
through a dedicated non-GUI entrypoint. Previously the frozen app interpreted
the `-m empy_studio.verification_pipeline` arguments as GUI arguments, causing
valid projects to fail Verification and enter a pointless repair loop. Python
project checks also select a host `python3`/`python` interpreter when the app
is frozen, while an unavailable interpreter remains a visible failed check.

The full suite and packaged macOS acceptance cover this path. The acceptance
provider is deterministic and local; no live model call is used.

## Previous release context

# Empy Studio 0.1.60 — bounded provider completion accounting

This patch fixed a false failure observed when Codex completed a scoped file
change but its final fresh-token accounting landed 270 tokens above the locked
economy node allocation. The completion allowance from that release has been
removed in 0.1.62; the overage is now kept as an explicit budget failure and
sent through verified recovery.

## Previous release context

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
