# Architecture

Empy Studio separates durable project knowledge from short-lived agent context.

```text
                 Project Vault
                      │
Request → Project Brain → Planner → Task Graph → Agent Host
                      │              │
          bounded Context Packs  Handoffs
                      │              │
                      └── Verification ──┐
                                        ↓
                              Release Integrator
                                        ↓
                              Synchronized Release
                                        ↓
                                Validated Learning
```

## Core modules

### Orchestrator

Creates dependency-aware tasks, execution waves, agent roles, and write scopes.

### Project Brain and context selector

`core/project_brain.py` maintains a safe, incremental manifest of project files,
lightweight language/import/symbol hints, and content hashes. On a follow-up
ticket, unchanged records are reused and the context selector consumes the
manifest instead of walking the repository again. The selector still reads
only the small files selected for the approved agent packs.

The local benchmark compares a full-repository estimate with the bounded packs.
It is deliberately provider-neutral; provider-reported usage is captured
separately by the driver and never presented as a local estimate.

### Runtime verifier

Runs local commands, verifies artifacts, records checks that failed, and preserves environment-dependent checks as pending.

### Learning

Merges validated, reusable lessons. Project-specific preferences stay in the Project Vault.

### CLI

Provides a small host-neutral interface:

```text
empy plan
empy learn
empy verify
```

## Boundary with coding agents

Empy Studio is the control layer, not the language model. Codex or another host performs model-driven implementation. Empy Studio preserves scope, continuity, ownership, evidence, and release discipline.
