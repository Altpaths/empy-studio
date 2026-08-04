# Changelog

All notable changes to Empy Studio are documented here.

## [Unreleased]

### Added

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

## [0.1.0] — Developer Preview

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
