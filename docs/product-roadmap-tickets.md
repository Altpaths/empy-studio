# Empy Studio Product Roadmap and Ticket Contract

Status: approved for implementation on 2026-08-09  
Canonical repository: `Altpaths/empy-studio`  
Execution branch: `codex/product-continuity-roadmap`

This document is the durable record of the product ticket list approved for
the Empy Studio project. It replaces memory-only planning. A ticket is not
complete until its acceptance criteria are implemented, tested, and recorded
in the delivery evidence.

## Product decisions

- The GitHub `main` repository is the canonical source of truth. The original
  `empy-studio-main.zip` is an immutable audit baseline, not a second source
  tree.
- The Ticket 16 macOS package is the source of the guided web UI and project
  import/export work. Its code is merged selectively; it must not introduce a
  second copy of the core or a second persistence system.
- v1 is local-first and macOS-first. Codex is the first production provider;
  other providers use the same adapter contract and are enabled only after
  passing the same acceptance gates.
- The application workspace remembers projects, tickets, runs, decisions,
  baselines, and releases across restarts.
- A generated project delivery is a single-root ZIP that can be extracted into
  the destination project location. Reports and checksums are delivered beside
  the project artifact or in an explicitly documented metadata directory; a
  project ZIP must never hide the project inside another ZIP.
- No provider, agent, or release operation may silently commit, push, merge,
  publish, or expose secrets.

## Ticket sequence

| ID | Ticket | Definition of done | Dependencies | Priority |
|---|---|---|---|---|
| T00 | Immutable baseline and audit | Source hashes, manifests, differences, and test baselines are recorded; original inputs are untouched. | — | P0 |
| T01 | Canonical source reconciliation | The GitHub repository contains one shared core, the guided UI sources, and a documented merge map. | T00 | P0 |
| T02 | Product contracts and test harness | Project, Ticket, Run, Release, Provider, Report, and evidence contracts are versioned and tested on supported Python versions. | T01 | P0 |
| T03 | Persistent workspace and Project Vault | Closing and reopening the app preserves projects, tickets, runs, settings, baseline, and release history. | T02 | P0 |
| T04 | Project lifecycle | A user can create, import, reopen, switch, and start a separate project without losing another project's state. | T03 | P0 |
| T05 | Ticket continuity | A project has a durable backlog with status, dependencies, notes, acceptance criteria, and sequential follow-up tickets. | T03, T04 | P0 |
| T06 | Baseline and accepted releases | An accepted run becomes the next baseline, with a traceable diff and rollback/revert evidence. | T05 | P0 |
| T07 | Provider abstraction and settings | Provider capabilities, authentication state, settings, and usage are exposed through one interface without storing secrets in project files. | T02, T03 | P1 |
| T08 | Production Codex driver | Codex execution supports preflight, bounded permissions, cancellation, timeout, structured events, usage, and actionable failures. | T07 | P0 |
| T09 | Incremental Project Brain | Local indexing records file hashes, languages, imports/symbols, project markers, and reusable summaries; unchanged files are not rescanned unnecessarily. | T03, T04 | P0 |
| T10 | Context and token controller | Context selection combines ticket relevance, file ownership, imports/symbols, diff, cached summaries, and a measured provider budget. Invalid or irrelevant plans are blocked. | T05, T09 | P0 |
| T11 | Planner and bounded Agent Graph | Roles and waves are selected from project evidence; every write file has one owner and a zero-writable task cannot run. | T07, T09, T10 | P0 |
| T12 | Execution, handoff, resume, and reports | Agent waves produce durable structured reports, handoffs, logs, retry state, and a resumable run history. | T08, T11 | P0 |
| T13 | Verification and review | Tests/build/lint, changed-file review, accept/revert, conflict detection, and verification evidence are available in the product flow. | T06, T12 | P0 |
| T14 | Direct project exporter | Export produces a safe single-root project ZIP, excludes secrets and temporary files, writes a manifest/checksum, and passes extract/re-import tests. | T06, T13 | P0 |
| T15 | Bilingual product UI | Persian and English cover project selection, ticket intake, plan, run, report, review, history, settings, and errors. | T03, T05, T12, T13, T14 | P0 |
| T16 | Security and privacy hardening | Path validation, secret scanning, symlink policy, provider permission boundaries, installer verification, and audit logs are tested. | T08, T14, T15 | P0 |
| T17 | Real-project acceptance | A non-developer completes two sequential tickets on one project, a new project flow, reopen, review, revert, and export without terminal commands. | T04–T16 | P0 |
| T18 | Open-source distribution | CI, supported Python matrix, macOS packaging, signing/notarization strategy, checksums, release notes, license, contribution docs, and downloadable assets are verified. | T17 | P0 |

## Acceptance scenario

The release is not called product-ready until this scenario passes on a clean
machine and on a real project:

1. Install Empy Studio and open it without a terminal.
2. Import or select an existing project and create its local Project Vault.
3. Add Ticket 1 in natural language and review the generated plan, agents,
   owned files, context, and token budget.
4. Run the approved graph, inspect agent handoffs and verification evidence,
   then accept or revert individual changes.
5. Export a single-root project ZIP and verify its checksum, extraction, and
   re-import.
6. Close and reopen Empy Studio; the project, Ticket 1, run, and release remain
   available.
7. Add Ticket 2 to the same accepted project. Only relevant incremental
   context is selected and the second run remains traceable to the first.
8. Create a new project and verify that its history and baseline are isolated.

## Execution policy

- Work is performed in a staging checkout and a bounded branch; the canonical
  baseline is never edited in place during an implementation wave.
- Each wave has disjoint file ownership, a consolidated review, real test
  output, and an explicit integration decision.
- A report must distinguish `FACT`, `INFERENCE`, `UNKNOWN`, and `BLOCKED`.
- No test is described as passing unless it actually ran.
- The final release must list tests run, tests not run, external checks,
  remaining risks, artifact paths, and SHA-256 checksums.

## Current wave

The first implementation wave starts with T00/T01/T02 and the P0 continuity
path. The current GitHub repository already contains substantial work through
the earlier runtime, provider, synchronization, verification, and review
tickets. The remaining work is to reconcile the guided GUI with that canonical
core, make its state durable, support follow-up tickets, and prove the direct
project delivery flow.

## Continuity hardening tickets

| ID | Scope | Current state |
|---|---|---|
| T19 | Consolidated per-agent report, usage provenance, evidence, verification, review, and export status | Implemented and tested |
| T20 | Canonical bilingual Web Desktop path, folder/ZIP import, Codex readiness, accessibility labels, and legacy Tk boundary | Implemented and tested |
| T21 | Bounded parallel waves, dependency-safe scheduling, capacity, retry/time evidence, and Codex ownership audit | Implemented and tested |
| T22 | Claude Code CLI adapter behind the provider contract, external credential handling, bounded edits, timeout/cancel | Implemented and tested with a local fake CLI; live CLI/auth remains environment-dependent |
| T23 | Multi-project token/time benchmark, CI regression thresholds, clean-install checks, and stable macOS signing/notarization gates | Implemented as release gates; Apple signing/notarization must run with repository release secrets |
