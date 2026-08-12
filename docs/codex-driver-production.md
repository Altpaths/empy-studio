# Ticket 8 — Production Codex Driver

## Purpose

Ticket 11 connects the approved Empy execution graph to the local OpenAI Codex
CLI. The runtime is non-interactive, bounded by the approved graph, observable
from the desktop application, cancellable, and evidence preserving.

## Preflight

Before a run starts, Empy:

1. resolves the `codex` executable from `PATH` and common macOS locations;
2. reads `codex --version`;
3. confirms that `codex exec` is available;
4. checks `codex login status`;
5. inspects command diagnostics for known host PATH-alias, app-server, state,
   and sandbox initialization failures;
6. refuses to start when installation, authentication, or host readiness is
   unavailable.

Preflight never starts a model turn, so this readiness check does not consume
provider tokens. Raw command output is kept only in the normal execution
evidence; the readiness result exposes a stable diagnostic and remediation.

The UI returns a concrete remediation instead of a raw process failure.

## Execution contract

Each Agent Run Graph node receives:

- one approved objective;
- one bounded Context Pack;
- its explicit owned and read-only paths;
- protected-path exclusions;
- its locked token allocation;
- dependency ordering from Ticket 10.

Empy starts `codex exec` with JSONL output, passes the prompt through standard
input, records the final agent message separately, and selects either
`workspace-write` or `read-only` sandbox mode from the node ownership contract.
Small, explicitly scoped implementation nodes disable extra reasoning effort;
higher-budget or sensitive nodes use low reasoning. All graph nodes ignore
unrelated user config and carry an enforceable fresh-token safety limit. The
driver stops an active node when structured usage exceeds that limit and
reports `budget_exceeded`; final-turn accounting is recorded as a warning so a
completed implementation is not falsely marked failed.
The runtime does not ask Codex to commit, push, merge, tag, publish, or modify
Git remotes.

## Safety and scope audit

For Git projects, execution requires a clean worktree. Empy snapshots Git state
before and after every node. A run fails immediately when Codex changes a path
outside the node's ownership or changes Git history. Remaining dependency nodes
are recorded as skipped.

The CLI sandbox is project-wide when writes are required; therefore the Git
scope audit is a second, deterministic enforcement layer. Non-Git projects still
receive the bounded prompt and sandbox, but do not have Git-based scope evidence.

## Observability and evidence

Every node stores:

- `command.json`;
- raw `events.jsonl`;
- `stderr.log`;
- `final-message.md`;
- mapped terminal status and error code;
- reported session/thread ID;
- audited changed-file list.

The workspace stores graph-run summaries in `codex-runs.json`. The desktop Runs
page displays live progress, node results, artifact paths, and understandable
errors.

## Runtime controls

- default node timeout: 1,800 seconds;
- explicit cancellation from the desktop;
- process-group termination on POSIX systems;
- fresh-token limit enforcement based on provider-reported input/output usage;
- separate total, fresh-input, cached-input, and output usage reporting;
- remaining graph nodes are skipped after failure, cancellation, timeout, or a
  scope violation;
- only one active Codex graph run per desktop controller.

## Error mapping

Empy distinguishes installation, authentication, permission, rate-limit,
network, sandbox, malformed-output, launch, timeout, cancellation, dirty
worktree, scope violation, and generic process failures.

Host-level preflight failures are returned as `sandbox_error` with an explicit
remediation. Empy never silently changes a node to `danger-full-access`.

## Scope boundary

Ticket 8 implements the production Codex driver only. Ticket 7 remains
responsible for provider-neutral driver selection and settings. Patch
synchronization and conflict resolution remain outside this ticket.
