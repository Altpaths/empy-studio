## Unreleased

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
