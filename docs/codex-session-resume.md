# Codex Session Resume and Evidence Store

Ticket 5.5 continues a previously completed or failed non-interactive Codex
thread without discarding earlier evidence.

## Resume command

The adapter uses the official non-interactive resume form:

```text
codex exec --json ... resume <SESSION_ID> -
```

The follow-up prompt is sent through standard input.

## Evidence index

Each run stores `evidence/index.json`. The index includes the initial turn and
every later resume turn:

```text
evidence/
  index.json
  events.jsonl
  stderr.log
  final-message.md
  command.json
  resume-0001-events.jsonl
  resume-0001-stderr.log
  resume-0001-final-message.md
  resume-0001-command.json
```

Each indexed turn records its sequence, kind, status, thread ID, return code,
event count, and evidence paths.

## Guarantees

- Resume requires a persisted `thread_id`.
- Only completed or failed runs can be resumed.
- Earlier evidence is never overwritten.
- Resume sequences increase monotonically.
- Manifest state transitions through `running`.
- Timeouts, malformed JSONL, execution failures, and non-zero exits are
  preserved.
- The existing thread ID is retained when a resume stream does not emit a new
  `thread.started` event.
- No credential files are read and `shell=True` is never used.
