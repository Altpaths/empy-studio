# Execution Plan

## Stage 0 — clean baseline

Create this independent Laravel tree, lock dependencies, and prove the default
runtime works. Keep old releases and unrelated fixtures outside the tree.

## Stage 1 — domain and import

Add project, ticket, run, event, and artifact records. Implement secure ZIP
import, project indexing, hashes, and an isolated workspace per project.

## Stage 2 — planning and context

Implement deterministic target discovery, ownership validation, graph
fingerprints, and a context ledger that sends only relevant changed files.

## Stage 3 — providers and execution

Implement local Ollama and OpenAI-compatible adapters, structured patch output,
provider routing, and progress-aware recovery. No provider is activated without
configuration.

## Stage 4 — verification and delivery

Verify changed files, syntax where supported, scope, and acceptance criteria.
Create a path-preserving ZIP and checksum only after verification.

## Stage 5 — simple UI and hardening

Provide a small upload/ticket/run/status/download flow and a matrix of clean
download, existing-file, text, section, API, provider-failure, and ownership
failure scenarios.

## Release gate

Do not publish to GitHub until the full test matrix, clean extraction smoke test,
and final release report pass. Publication will use a dedicated branch/tag so
the historical Python baseline remains recoverable.
