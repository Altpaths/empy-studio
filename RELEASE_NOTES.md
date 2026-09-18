# Empy Studio 0.1.69 — semantic chart scope and preflight contract repair

This release closes the failure mode where a PHP chart ticket selected only
CSS/JavaScript assets and left the page that actually renders the chart outside
the writer's ownership. Persian bank, account, pie/donut, percentage, and 3D
terms now guide bounded selection. A chart pack is guaranteed to contain the
most relevant page/template and, when present, one style and one behavior
asset, with deterministic ownership for the selected PHP page.

Verification now scans bounded project test/support directories before any
provider inspection. When a PHP application has `index.php` but a hand-written
check still references a missing root `index.html`, Empy repairs only proven
root path expressions in the isolated copy and leaves subpage `index.html`
references unchanged. Ambiguous contracts remain an explicit preflight error;
Empy never creates a fake entry page.

Validation for this release: 1015 tests, Ruff, and mypy pass locally. The
provider is not required for these checks.

## Previous release context

# Empy Studio 0.1.68 — stop redundant Discovery token spend

This patch fixes the reproduced failure where a Persian implementation request
for a selectable asset chart was classified as a read-only audit. Empy now
routes that imperative directly to the bounded frontend/backend graph, so the
provider does not spend a full Discovery turn before any writer can run.

Automatic recovery also preserves the failed implementation owner and carries
the existing Project Brain/failure handoff forward without replaying
read-only Discovery. Token-budget retries use a smaller, explicit context cap
so a retry cannot become more expensive than the failed attempt.

The full regression suite, strict Ruff lint, mypy, Python compile checks, and
provider-free context/token benchmarks are run for this release candidate.
Live provider billing, DirectAdmin extraction, and Apple notarization remain
external checks.

## Previous release context

# Empy Studio 0.1.67 — isolate project-level Verification failures

Empy now compares a failed whole-project Verification result with the exact
files changed by the active ticket. A chart or asset ticket is no longer sent
through repeated Agent discovery when an older site-audit contract fails on an
unrelated entry point such as `index.html` versus `index.php`.

The finding remains in the durable failure archive, the UI explains that it is
a separate project-level blocker, automatic repair is disabled for that
finding, and the current ticket cannot produce a ZIP until the project check is
resolved and Verification passes. Generic diagnostics without a concrete
project marker remain retryable so this guard does not hide a real ticket bug.

The full regression suite (1007 tests) and Python compile checks pass locally.
Provider billing, DirectAdmin extraction, and Apple notarization still require
their respective external environments.

# Empy Studio 0.1.66 — root-cause recovery routing and deterministic static repair

Empy now carries multiline Verification and execution diagnostics into the
bounded recovery context. When a check names `public_html/assets/home.css`,
that exact stylesheet becomes the frontend repair owner; the previous ticket's
unrelated JavaScript files are not selected again.

Before any provider inspection, the isolated project receives one narrow,
deterministic repair for a stylesheet that refers to `assets/foo` from inside
`assets/` while the existing `assets/foo` file is present. No placeholder file
is created and ambiguous references remain a visible Verification failure.

The full regression suite, strict lint, type checking, and compile checks pass
locally. Provider billing, DirectAdmin extraction, and Apple notarization still
require their respective external environments.

## Previous release context

# Empy Studio 0.1.65 — durable failure memory and duplicate-run prevention

Empy now keeps a bounded, project-scoped failure ledger in the local workspace.
It stores normalized causes, relative targets, and limited evidence rather than
provider transcripts, credentials, or absolute host paths. Repeated observations
are coalesced across tickets and application restarts.

Before inspecting or invoking a provider, Empy compares the current graph target
and isolated project snapshot with confirmed open failures. An unchanged repeat
is stopped locally with a clear bilingual explanation, so the provider does not
spend tokens on the same known failure. A real change to the isolated target or
snapshot is allowed to proceed. Credentials, permissions, and dependencies stay
re-checkable because their external state can change.

Failure memory records every independent Verification finding, feeds only a
bounded relevant handoff into later planning, and closes only after final
Verification passes with explicit evidence. The UI exposes the cause and next
action while keeping technical evidence optional. Normal workspace launches
retain project memory; `--clean` launches intentionally start empty.

The full regression suite (1003 tests), strict type/lint/compile checks,
packaged arm64 app build, normal acceptance (6/6), recovery acceptance (8/8),
and deterministic memory audit passed locally. Live provider billing and Apple
notarization were not claimed.

## Previous release context

Empy now maps PHP frontend tickets to the real entry point and existing asset
files. A virtual `index.html` target is created only when the request is
actually about the homepage, so an asset or chart ticket cannot fail merely
because a PHP project does not contain that file.

When a provider or graph stops with a generic no-change error, Empy preserves
the bounded Agent report, classifies the concrete blocker (including ownership
and layout mismatches), and passes that evidence into the recovery ticket.
The web UI presents one short bilingual finding and next action; raw provider
errors and run logs remain available only under collapsed technical details.

The full regression suite (982 tests), Python compile check, Ruff, and
JavaScript syntax check passed locally. No provider call is made by the test
suite.

## Previous release context

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
# Empy Studio 0.1.70 — bounded Persian chart routing and terminal UI state

This patch fixes the exact run reproduced from a local project URL. A Persian
request such as «نمودار دایره ای بخش بانک هارو سه بعدی کن» is now classified as
an implementation request. When deterministic Verification is available, the
graph contains only the bounded frontend writer; redundant provider Discovery
and Quality passes are removed, reducing repeated context and token spend.

The web client also stops polling when a run has ended and recovery is only
ready for a user-visible next step. It no longer presents a failed run as
«در حال اجرا» indefinitely.

Validation for this patch includes the full regression suite, strict Ruff,
mypy, JavaScript syntax checking, and the existing macOS acceptance workflow.
