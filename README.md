# Empy Studio

**A lightweight operating layer for coding agents — from an incomplete project to a bounded, verified, synchronized release.**

Empy Studio was created for a practical problem: giving a coding agent a half-finished project should not require repeating the full history, scanning the whole repository for every task, approving every small step, or manually merging disconnected outputs.

Empy Studio keeps the durable context small and explicit:

```text
Project + Project Vault + Request
                ↓
        bounded task graph
                ↓
      scoped agent execution
                ↓
       verification and sync
                ↓
        complete release
```

## Why it exists

Coding agents are capable, but project work becomes expensive and unreliable when context is repeatedly reconstructed. Common failure modes include:

- repeated discovery and re-uploading;
- unnecessary repository-wide scanning;
- unrelated file changes;
- parallel agents editing the same file;
- UI implementation before visual decisions are locked;
- tests reported without execution evidence;
- patches that never become a synchronized release.

Empy Studio addresses these failures with a small set of enforceable contracts.

## What it provides

- **Project Vault** — a working persistent baseline with source snapshot, manifest, decisions, tickets, and release history.
- **Task orchestration** — dependency-aware tasks and execution waves.
- **File ownership** — one write owner per file in each wave.
- **Agent-neutral contracts** — usable with Codex, Claude Code, or another
  coding-agent host.
- **Quality gates** — design, security, QA, synchronization, and release checks.
- **Runtime verification** — command, artifact, and external-check status tracking.
- **Validated learning** — reusable patterns are promoted only after evidence.
- **Delta delivery** — a verified ZIP containing only files changed since the
  imported baseline, with the full isolated copy retained for testing.
- **Incremental Project Brain** — unchanged project records are reused and
  bounded Context Packs avoid repeating repository-wide discovery on each
  ticket.
- **Token evidence** — bounded local context estimates and provider-reported
  usage are shown separately; missing provider usage is never guessed.

Claude Code is available through the provider registry when its CLI is
installed and `ANTHROPIC_API_KEY` is configured outside the project. The
guided Finder flow remains Codex-first until provider-neutral streaming and
verification events are available for every provider.

## Designed to stay small

Empy Studio is intentionally not an all-purpose agent framework. A capability belongs in the core only when it measurably reduces:

- token consumption;
- repeated work;
- delivery risk;
- context reconstruction;
- merge and release friction.

Everything else should remain optional.

## Quick start

Requirements: Python 3.10+ on macOS, Linux, or Windows.

```bash
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
pytest
```

Launch the bilingual guided desktop UI locally:

```bash
empy-web
```

The UI is local-only, keeps its SQLite workspace under the platform's per-user
application-data directory, and works on an isolated project copy. Use the
folder or ZIP buttons in the browser on all supported platforms; the path box
remains available for local automation. See
[`docs/web-desktop.md`](docs/web-desktop.md) for the product flow and API
boundary.

Inspect the CLI:

```bash
empy --help
```

Create a persistent Project Vault:

```bash
empy vault init \
  --project-root /path/to/project \
  --vault /path/to/empy-vaults/project-id \
  --project-id project-id \
  --name "Project Name"
```

Create an execution plan:

```bash
empy plan   --project examples/project.json   --request examples/request.json
```

Merge validated learning:

```bash
empy learn   --graph examples/graph.json   --sprint examples/sprint.json
```

Run local and external-aware verification:

```bash
empy verify   --manifest examples/runtime-manifest.json
```

Build a compact context package:

```bash
empy context build \
  --vault ./project_vaults/my-project \
  --request ./request.json \
  --output-dir ./context/worker-1 \
  --max-bytes 64000
```

## How to use it with a coding agent

Place Empy Studio's operating files in the project root or provide them to the primary coding-agent session. The primary agent should:

1. load `EMPY.md` and `AGENTS.md`;
2. create or load the Project Vault;
3. produce one bounded plan;
4. assign exact read and write scopes;
5. collect handoffs;
6. run verification;
7. synchronize the project;
8. deliver one verified change-only deployment release.

The host executes model-driven work; Empy Studio controls scope, evidence, continuity, and release discipline.

## Repository structure

```text
src/empy_studio/    Core orchestration, learning, verification, and CLI
examples/           Minimal input examples
tests/              Automated tests
docs/               Architecture, setup, and threat model
.github/            CI and contribution templates
EMPY.md             Operating principles for humans and agents
AGENTS.md            Agent execution contract
```


## Definition of Done and release building

Evaluate completion criteria:

```bash
empy done
```

Build a synchronized release:

```bash
empy release validate \
  --manifest release-manifest.json \
  --changelog CHANGELOG.md

empy release build \
  --manifest release-manifest.json \
  --source-root . \
  --include src \
  --include tests \
  --include docs \
  --include examples \
  --include README.md \
  --include README.fa.md \
  --include CHANGELOG.md \
  --include LICENSE \
  --include pyproject.toml \
  --include release-manifest.json \
  --changelog CHANGELOG.md \
  --output-dir dist
```

The builder creates a versioned ZIP, JSON manifest, SHA-256 checksum, and release notes. It does not create a Git tag or publish remotely without a separate explicit action.

Build and verify real distribution assets locally:

```bash
python scripts/build_release_assets.py --output build/release-assets
python scripts/verify_release_assets.py build/release-assets/release-assets.json
```

On macOS, the Finder-launchable app is built separately with the release
dependencies. The command fails closed when PyInstaller or the app bundle is
missing; signing and notarization remain explicit release gates. See
[`docs/release-artifacts.md`](docs/release-artifacts.md).


## Multi-Agent Runtime

Run a dependency-aware set of bounded agents:

```bash
empy runtime run   --manifest examples/runtime.json   --output-root .empy-runtime
```

The runtime selects agents by capability, preserves task handoffs, isolates agent
memory, applies retries and subprocess timeouts, and records complete run state.
It remains provider-neutral: model execution is supplied through adapters.

## Capability Graph

Plan explainable agent assignments from aliases, prerequisites, capacity,
priority, reliability, and cost:

```bash
empy capabilities plan --manifest examples/capabilities.json
```

The scheduler integrates with the Multi-Agent Runtime and records why each
agent was selected.

## Plugin SDK

Empy Studio plugins are provider-independent `.empy-plugin` artifacts with:

- validated manifests and compatibility requirements;
- SHA-256 integrity records;
- optional signature metadata;
- metadata-only discovery;
- isolated loading;
- atomic runtime-hook registration.

```bash
empy plugin inspect   --package example-plugin.empy-plugin   --empy-version 1.0.0
```

See `docs/plugin-sdk.md` for the complete architecture and contract.

## Plugin Package Manager

Empy Studio installs verified `.empy-plugin` artifacts into a transactional,
versioned Store with source resolution, upgrade, rollback, removal, listing,
health inspection, and CLI management.

```bash
empy plugin install   --source example.empy-plugin   --store ~/.local/share/empy-studio/plugins   --empy-version 1.0.0
```

See `docs/plugin-package-manager-v1.md` for the complete architecture.

## Status

**v0.1.0 — Developer Preview**

The current release provides a working CLI, task-graph generation, ownership-conflict detection, evidence-backed learning, and runtime-aware verification. Public interfaces may evolve before v1.0.

## Principles and documentation

- [Operating principles](EMPY.md)
- [Architecture](docs/architecture.md)
- [Context Builder](docs/context-builder.md)
- [Project Vault](docs/project-vault.md)
- [Getting started](docs/getting-started.md)
- [Environment setup](docs/environment.md)
- [Threat model](docs/threat-model.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Author

**Azadeh Sharifi**  
[empy.ir](https://empy.ir)

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Codex Workflow Adapter

Empy Studio supports bounded, evidence-backed Codex workflows with
materialized run instructions, environment diagnosis, non-interactive
execution, resumable sessions, manual fallback, and CLI management.

```bash
./.venv/bin/empy codex --help
```

See `docs/codex-workflow-adapter-v1.md` for the complete architecture.

## Release Manager

Empy Studio includes a controlled Release Manager with Semantic Versioning,
changelog validation, deterministic archives, Artifact Index and SHA-256,
controlled tags, GitHub Actions guards, GitHub Release synchronization, asset
verification, latest-release policy, and rollback metadata.

```bash
./.venv/bin/empy release --help
```

See `docs/release-manager-v1.md`.

## Distribution and Installer

Empy Studio generates verified standalone installers for macOS, Linux, and
Windows, plus matching uninstallers and direct GitHub Release download maps.

```bash
./.venv/bin/empy distribution --help
```

See `docs/distribution-installer-v1.md`.
