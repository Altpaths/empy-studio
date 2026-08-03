# Codex Workflow Adapter v1

Ticket 5 completes the Codex integration layer for Empy Studio.

## Architecture

```text
Project Vault
  → bounded Context Package
  → Codex Task Contract
  → AGENTS.md + prompt materialization
  → Environment Doctor
  → codex exec --json
  → Evidence Store
  → Session Resume
  → Runtime Dispatcher
  → Verification or Manual Handoff
```

## Components

### Workflow contract

The contract defines:

- task identity;
- objective;
- acceptance criteria;
- allowed and forbidden paths;
- verification commands;
- execution constraints;
- sandbox and approval policy.

### Materializer

Each run receives an isolated directory containing:

```text
AGENTS.md
prompt.md
manifest.json
context/
evidence/
```

### Environment Doctor

The doctor checks:

- Codex executable availability;
- Codex version;
- `codex exec` availability;
- authentication through `codex login status`;
- project root;
- materialized run files;
- Git repository and worktree status.

Credential files are never read.

### Initial execution

The adapter runs Codex through an argument list without `shell=True`:

```text
codex exec --json ... -
```

The prompt is passed through standard input.

### Evidence

Each execution preserves:

- JSONL events;
- stderr;
- final assistant message;
- command metadata;
- persisted Run Manifest.

### Resume

Completed or failed runs with a persisted thread ID can continue through:

```text
codex exec --json ... resume <thread-id> -
```

Every resume turn receives a unique sequence and never overwrites previous
evidence.

### Runtime integration

The runtime dispatcher provides:

```text
prepared
  → doctor ready
      → execute
  → doctor not ready
      → manual_required

completed or failed + follow-up prompt
  → resume
```

### Manual fallback

When Codex is unavailable, Empy Studio writes a manual handoff record rather
than discarding the run or losing the task context.

## CLI

```bash
empy codex doctor --manifest RUN/manifest.json
empy codex run --manifest RUN/manifest.json
empy codex resume --manifest RUN/manifest.json --prompt "Continue"
empy codex manual --manifest RUN/manifest.json --reason "..."
empy codex status --manifest RUN/manifest.json
```

## Security model

The v1 adapter:

- never uses `shell=True`;
- defaults to `workspace-write`;
- requires non-interactive runs not to wait for approval;
- does not read Codex credential files;
- does not write credentials into evidence;
- preserves malformed output and failed execution evidence;
- isolates run inputs and evidence by run ID.

## Scope boundary

Ticket 5 does not implement:

- a hosted Codex service;
- shared remote session storage;
- marketplace distribution;
- automatic Git commit or merge;
- unattended execution with `danger-full-access`.

Those capabilities require separate policies and later tickets.
