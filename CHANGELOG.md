# Changelog

All notable changes to Empy Studio are documented here.

## [Unreleased]

### Added

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
