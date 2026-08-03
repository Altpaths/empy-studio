# Codex Workflow Adapter

The Codex Workflow Adapter connects Empy Studio's Project Vault, Context
Builder, Runtime, and Evidence model to the official Codex CLI.

## Architecture

```text
Project Vault
  → bounded Context Builder output
  → Codex Task Contract
  → materialized AGENTS.md and prompt
  → codex exec
  → JSONL event evidence
  → resumable session state
  → verification
```

## Responsibility boundary

Empy Studio owns:

- task scope;
- acceptance criteria;
- allowed and forbidden paths;
- context selection;
- execution policy;
- evidence storage;
- verification;
- fallback when Codex is unavailable.

Codex owns:

- repository inspection;
- code editing;
- command execution inside the selected sandbox;
- the agent loop;
- session and thread execution.

## Execution policy

The default automated policy is:

- non-interactive mode;
- `workspace-write` sandbox;
- no approval prompts;
- bounded timeout;
- no web search unless explicitly enabled.

`danger-full-access` is represented in the contract but is never selected by
default.

## Current stage

Ticket 5.1 defines the stable Workflow Contract and Run Manifest. It does not
execute Codex.
