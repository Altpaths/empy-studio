# Codex Exec Adapter

Ticket 5.4 executes one prepared Codex run through the official non-interactive
CLI.

## Command model

The adapter invokes:

```text
codex exec
  --json
  --cd <project-root>
  --sandbox <policy>
  --ask-for-approval <policy>
  --output-last-message <evidence/final-message.md>
  -
```

The final `-` tells Codex to read the prompt from standard input.

Run-specific `AGENTS.md` content is combined with `prompt.md` and sent through
stdin. This avoids modifying or overwriting a repository's existing
`AGENTS.md`.

## Evidence

Each run records:

- `events.jsonl`;
- `stderr.log`;
- `final-message.md`;
- `command.json`;
- updated `manifest.json`.

The adapter extracts the session identifier from `thread.started` when present.

## State transitions

```text
prepared → running → completed
                   ↘ failed
```

Timeouts, process-start failures, malformed JSONL, and non-zero exit codes are
recorded without hiding the original evidence.

## Security

The adapter:

- never uses `shell=True`;
- passes arguments as an argv list;
- defaults to `workspace-write`;
- requires `never` approval policy for non-interactive execution;
- does not read credential files;
- does not place API keys in command evidence.
