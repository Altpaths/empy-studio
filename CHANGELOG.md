## [Unreleased]

## [0.1.20] - 2026-08-12

### Follow-up ticket baseline

- Create an internal checkpoint after a user accepts a complete review so a
  follow-up ticket can run without asking the user to commit changes.
- Keep the checkpoint inside Empy's isolated copy; original project files,
  remotes, and exported ZIP contents remain outside the checkpoint history.
- Add acceptance coverage for a second ticket after an accepted first ticket.

## [0.1.19] - 2026-08-12

### Deterministic agent selection

- Match planner keywords as complete words or phrases so words inside file
  names and ordinary prose cannot activate unrelated agent roles.
- Keep actionable custom tickets on the generic bounded writer path when no
  domain-specific role is actually requested.
- Add regression coverage for a real Node ticket containing source and test
  paths.

## [0.1.18] - 2026-08-12

### Test-file ownership

- Include test files in a writer's bounded context only when the ticket
  explicitly asks to change or update those tests.
- Assign requested Python, JavaScript, TypeScript, and PHP test files to the
  single implementation owner while keeping Quality Agent read-only.
- Add a regression test covering source and test-file ownership for a custom
  ticket.

## [0.1.17] - 2026-08-12

### Actionable custom tickets

- Route natural-language change, fix, update, and Persian implementation
  requests to a bounded writer agent instead of producing only read-only
  discovery and quality nodes.
- Keep audit and test-only requests read-only by distinguishing implementation
  verbs from inspection and verification language.
- Extend generic code ownership to common JavaScript, Markdown, library, and
  documentation paths while preserving narrower frontend ownership patterns.

## [0.1.16] - 2026-08-12

### Natural ticket requests

- Keep an actionable clause when a user combines the requested work and its
  safety constraint in one sentence.
- Split explicit Persian or English semicolon clauses before classifying
  constraints, so ordinary one-line tickets are not rejected as empty.

## [0.1.15] - 2026-08-12

### Reliable ticket submission

- Preserve the ticket draft while the web interface refreshes after an error
  or language/status update.
- Read and persist the current ticket input before submitting the plan so a
  visible request cannot be lost between the editor and the API call.
- Keep drafts scoped to the active project and clear them when starting over.

## [0.1.14] - 2026-08-11

### Persistent import review

- Persist the import review in the local workspace so excluded-file warnings
  survive restart and installation upgrades.
- Restore the warning level and categorized counts when an imported project is
  reopened instead of presenting an old, incomplete status.

## [0.1.13] - 2026-08-11

### Transparent project import

- Show imported and excluded item counts instead of reporting a filtered
  import as an unexplained success.
- Classify excluded metadata, dependencies, sensitive/runtime files, unsafe
  paths, and unreadable items without exposing local source paths.
- Keep the original project untouched and present a bilingual warning before
  the user continues with the isolated copy.

## [0.1.12] - 2026-08-11

### User-facing failure guidance

- Translate stale Verification evidence and failed project checks into a
  bilingual explanation of what happened and what the user should do next.
- Move raw gate and Verification output into an optional technical-details
  section instead of making it the primary error experience.
- Use friendly bilingual status labels in the result summary and keep raw
  blocker text out of the primary export status card.
- Expose structured guidance in the run report and cover stale-evidence and
  failed-check regressions with automated tests.

## [0.1.11] - 2026-08-11

### Structured failure guidance

- Expose bilingual explanations for stale Verification evidence and failed
  project checks.
- Keep the technical evidence available while giving users a clear next
  action.

## [0.1.10] - 2026-08-11

### Installer upgrade safety

- Replace the active installation symlink atomically on Unix instead of
  following an old directory symlink during upgrades.
- Refuse to overwrite an unexpected real file or directory at the active
  installation path.
- Make installer smoke verification fail when the active symlink points to a
  different version than the recorded installation state.

## [0.1.9] - 2026-08-11

### Verification restore safety

- Invalidate persisted Verification results created by an older or different
  verification contract instead of treating them as current passing evidence.
- Keep the release gate blocked until Verification is rerun and finalized.
- Show blocked export status and explain when there are no file changes to
  accept or restore.

## [0.1.8] - 2026-08-11

### Installer Python discovery

- Discover versioned interpreters such as python3.12 when the system
  python3 command points to an older unsupported Python version.
- Report the detected incompatible interpreter in the installer error instead
  of returning an ambiguous minimum-version failure.

## [0.1.7] - 2026-08-11

### Verification and release-gate correctness

- Detect nested application roots such as `public_html/` without changing the
  imported project layout, and run Composer checks from the real application
  root.
- Prevent missing Composer dependencies and failed project test scripts from
  being treated as a passing release gate.
- Separate provider/verification completion from ZIP readiness, report explicit
  export blockers, and reject export until verification and Review evidence are
  complete.
- Show when a project has no file changes but is ready for an explicit ZIP
  export instead of implying that a ZIP was already produced.
- Repair Python console-script paths after installer relocation so `empy-web`
  remains runnable from the installed version directory.

## [0.1.6] - 2026-08-10

### Verification continuation for plain PHP projects

- Detect PHP projects even when their source lives below the root and there is
  no root `index.php` or `composer.json`.
- Map safe `php -l` checks for plain PHP projects without Composer or PHPUnit,
  excluding dependencies, generated files, and Empy workspace data.
- Persist missing verification executables as failed evidence instead of
  crashing the run, and include common desktop/Homebrew tool paths.
- Keep unmapped verification as an actionable failed report instead of a dead
  end, with persisted diagnostics and an export gate.
- Show bounded, redacted verification failures in the bilingual UI and carry
  them into a new corrective ticket on the same isolated project.
- Give generic HTML and nested PHP files to the appropriate writing Agent so
  corrective plans do not fail during ownership assignment.

## [0.1.5] - 2026-08-10

### Desktop provider-path reliability patch

- Restored the Codex/Node runtime PATH for Finder-launched and other GUI
  environments with a sparse shell PATH, while keeping preflight and real
  execution on the same child-process contract.
- Added regression coverage for sparse GUI PATH detection and the installed
  npm Codex shim; real execution remains safely blocked when Codex is not
  available or authenticated.

## [0.1.4] - 2026-08-10

### Release automation patch

- Updated the Intel macOS GitHub Actions runner label to the currently
  supported hosted runner so multi-architecture release validation cannot
  remain queued on a retired label.

## [0.1.3] - 2026-08-10

### Cross-platform patch release

- Made web asset MIME types deterministic across operating systems so the
  browser UI is served identically on macOS, Linux, and Windows.
- Fixed the platform CI dependency setup and verified the full smoke matrix.

## [0.1.2] - 2026-08-10

### Tickets 24–26 — Cross-platform reliability hardening

- Made the guided Web Desktop the shared macOS, Linux, and Windows product
  path with per-OS persistent workspace locations.
- Added browser folder and ZIP uploads with bounded file/total sizes, traversal
  and sensitive-file filtering, isolated staging, and cleanup after import.
- Rejected system/user roots and macOS AppTranslocation sources before import;
  unreadable project members are reported as skipped instead of exposing raw OS
  tracebacks.
- Added Codex executable fallback selection so a translocated or broken CLI
  path does not block a valid PATH/Homebrew/user installation.
- Added bounded preflight output and host diagnostics for translocation,
  permission, and sandbox failures; UI errors are bilingual and path-safe.
- Added platform smoke CI for Ubuntu, macOS, and Windows plus contract tests
  for workspace paths, uploads, safe errors, and provider fallback.

## [0.1.1] - 2026-08-10

### Tickets 19–23 — Product continuity hardening

- Added consolidated per-agent reports with durations, role/status, provider
  usage provenance, local token estimates, safe evidence references, review,
  verification, export, and dependency-wave schedule data.
- Made the Web Desktop path the canonical bilingual Finder flow with folder/ZIP
  import, readiness refresh, accessible labels, and honest Codex remediation.
- Added bounded parallel execution for independent waves, scheduler capacity,
  deterministic handoff/memory commits, retry timing, and Codex-wide ownership
  audits for concurrent nodes.
- Added a real Claude Code CLI driver behind the provider contract. It reads an
  external `ANTHROPIC_API_KEY`, never persists the secret, and reports missing
  CLI/credential states honestly.
- Added three-project token/time benchmark thresholds to CI and retained clean
  install plus Apple signing, notarization, stapling, and Gatekeeper gates for
  stable macOS publication.

### Ticket 18 — Open-source distribution foundation

- Added a supported Python CI matrix with package build, clean wheel install,
  CLI/UI smoke checks, and release-asset verification.
- Added deterministic package and installer asset generation with SHA-256
  manifests that fail closed on mismatched or incomplete output.
- Added a real macOS Finder app build path through PyInstaller; unsigned and
  unnotarized artifacts remain explicitly classified as release candidates.
- Added release documentation that separates verified local behavior from
  credentials-dependent Apple signing, notarization, and clean-machine gates.

### Ticket 17 — Real-project acceptance and terminal run safety

- Added a deterministic PHP acceptance harness covering isolated import, two sequential tickets, reopen, Review accept/revert, verified ZIP export, and second-project isolation.
- Exercised the same flow against the read-only Holda witness; the original witness digest remained unchanged.
- Added durable Codex, Verification, and Review evidence links so terminal results can be reopened with the ticket.
- Added an authenticated bilingual Stop run action with bounded cancellation for Provider and project verification processes.
- Fixed early-cancellation races, verification hangs, stale terminal UI states, and misleading skipped-node status rendering.

### Ticket 16 — Security and privacy hardening

- Added `empy security audit` for deterministic, validated JSON security evidence.
- Redacted secret-like command output and dependency URL credentials before evidence persistence.
- Rejected symlinked source paths and skipped symlinked files during project digest and scans.
- Preserved explicit provider sandbox boundaries and verified installer/archive safety through the full test suite.

### Ticket 8 — Production Codex driver hardening

- Added no-token host preflight diagnostics for PATH-alias, app-server, state,
  and sandbox initialization failures.
- Propagated actionable `sandbox_error` readiness failures through the driver,
  graph runtime, and persisted run evidence.
- Updated the Codex adapter for the current CLI by removing the obsolete
  `--ask-for-approval` flag and adding an explicit trust-check bypass only for
  selected non-Git projects.
- Verified the real adapter with a read-only provider smoke on an isolated
  fixture; no project or Holda files were changed.
- Kept bounded sandbox selection and explicit `danger-full-access` behavior
  unchanged; no automatic safety downgrade is performed.

### Ticket 15 — Diff Review, Accept & Revert

- Added a Desktop Review Workspace with changed-file status and readable diffs.
- Added explicit per-file Accept decisions that preserve working-tree changes.
- Added safe Revert for tracked, staged, deleted, renamed, and untracked files.
- Added stale HEAD, stale file, and rename-source safety gates before decisions.
- Kept commit, push, merge, and release outside Review Workspace and under explicit user control.

### Ticket 14 — Verification Pipeline in UI

- Added project-aware verification mapping for Python, Laravel, Node, Rust, Go, and explicit `.empy/verification.json` manifests.
- Added streamed stdout and stderr for Tests, Build, and Lint panels inside Desktop.
- Added durable verification reports and per-check evidence files.
- Added a real Finalize gate that remains blocked until every verification check passes.

### Ticket 13 completion — Conflict UI

- Added a dedicated Desktop Sync workspace for persisted Sync Reports.
- Added conflict inspection with file, conflict type, hashes, and competing patches.
- Added explicit Apply Patch, Keep Current, and Manual Content decisions.
- Disabled ordered apply until every conflict has a user decision.
- Persisted decisions and final applied state through SyncWorkspaceAdapter.

# Changelog

All notable changes to Empy Studio are documented here.

## [Unreleased]

### Added

- provider-neutral Sync & Conflict Resolver with deterministic ordered patch queues
- Agent Dispatcher ownership enforcement before workspace changes
- protected-file, stale-base, invalid-operation, and duplicate-write detection
- explicit user resolutions: apply patch, keep current, or manual merged content
- atomic file writes, pre-apply workspace revalidation, and rollback on apply failure
- persistent Sync Reports for Desktop conflict review

- provider-neutral Driver Registry, Driver Manager, and persisted Driver Settings
- desktop capability matrix with honest available, disabled, and unavailable states
- replaceable default-provider selection without credential-secret persistence
- registered Codex, Claude, and Gemini provider slots with Codex as the implemented runtime

- production Codex CLI driver with installation and authentication preflight
- non-interactive JSONL execution with per-node session and command evidence
- dependency-ordered execution of approved Agent Run Graph nodes
- live desktop progress, cancellation, timeout, run history, and mapped provider errors
- clean-worktree and post-run file-ownership audits for Git projects

- provider-neutral Agent Dispatcher and persistent Agent Run Graph
- deterministic role and capability matching from approved plan steps
- single-writer file ownership with explicit read-only access
- dependency-aware execution waves and per-node token/context bindings
- desktop Agent Run Graph preview without provider execution

- pre-execution Token Budget Controller with economy, standard, and extended presets
- visible planning, agent, retry, handoff, reserve, and total hard limits
- immutable budget locking before execution and persistent budget workspace
- bounded retry and handoff counters with automatic stop decisions
- deterministic provider-neutral token estimation and per-agent allocation panel

- Desktop Context Selector for approved execution plans
- deterministic file relevance scoring per planned agent role
- bounded per-agent context packs with visible source previews
- Project Brain summary and persistent context-selection workspace
- sensitive-file, dependency-directory, symlink, binary, and size exclusions

- transactional Plugin Package Manager
- local, HTTP, HTTPS, file URL, and GitHub Release source resolution
- versioned Plugin Store with inventory, locks, and transaction journals
- install, upgrade, rollback, remove, list, and status operations
- complete Package Manager CLI and end-to-end lifecycle test

- stable Plugin SDK contracts and manifest validation
- `.empy-plugin` artifact format with SHA-256 integrity records
- metadata-only plugin discovery
- isolated plugin loading
- atomic agent, adapter, validator, and context-provider registration
- sample plugin and Plugin CLI commands

- Capability Graph and explainable Agent Scheduler
- capability aliases, implications, and prerequisites
- capacity, priority, reliability, and cost-aware ranking

- host-neutral Multi-Agent Runtime
- capability-based Agent Registry
- dependency DAG, handoffs, retries, timeout, and failure propagation
- persistent per-agent memory and run state
- command adapter contract and runtime example

- Definition of Done validation
- synchronized Release Builder
- versioned ZIP, manifest, SHA-256, and release notes

- Environment Doctor (`empy doctor`)
- Bootstrap workflow (`empy bootstrap`)
- Local quality validation (`empy validate`)

- persistent Project Vault baseline and source snapshot
- task-specific Context Builder with explicit byte budget and token estimate

- executable Project Vault initialization and status commands
- filtered baseline source snapshots
- file manifests with SHA-256 checksums
- durable project identity, decisions, tickets, and release records

## [0.1.0] - 2026-08-09

### Added

- Capability Graph and explainable Agent Scheduler
- capability aliases, implications, and prerequisites
- capacity, priority, reliability, and cost-aware ranking

- host-neutral Multi-Agent Runtime
- capability-based Agent Registry
- dependency DAG, handoffs, retries, timeout, and failure propagation
- persistent per-agent memory and run state
- command adapter contract and runtime example

- Definition of Done validation
- synchronized Release Builder
- versioned ZIP, manifest, SHA-256, and release notes

- persistent Project Vault baseline and source snapshot
- task-specific Context Builder with explicit byte budget and token estimate

- dependency-aware task planning
- execution waves
- file ownership conflict detection
- runtime command and artifact verification
- explicit pending state for external checks
- evidence-backed learning
- host-neutral CLI
- agent execution contract
- English and Persian documentation

### Status

The core is operational and tested. Public interfaces may change before v1.0.

### Codex Workflow Adapter

- added bounded Codex task contracts and run manifests
- added AGENTS.md and prompt materialization
- added Codex environment diagnosis
- added non-interactive `codex exec` adapter
- added JSONL evidence preservation
- added session resume and evidence indexing
- added runtime dispatch, manual fallback, and CLI commands
- added end-to-end lifecycle coverage

### Release Manager

- added Semantic Version and Release Manifest contracts
- added changelog validation
- added deterministic release archive construction
- added Artifact Index, SHA-256, size, and media-type verification
- added controlled annotated Git tags
- added GitHub Release creation and asset synchronization
- added latest-release strategy
- added CI publication guard
- added partial-publication rollback metadata
- added Release Manager CLI and end-to-end tests

### Distribution and Installer

- added macOS ARM64 and x86_64 installers
- added Linux ARM64 and x86_64 installers
- added Windows x86_64 PowerShell installer
- added environment and Python preflight
- added SHA-256 package verification
- added installer-state based uninstallers
- added GitHub Release distribution synchronization
- added direct download link maps preserving GitHub asset counters
- added Distribution CLI and end-to-end tests
