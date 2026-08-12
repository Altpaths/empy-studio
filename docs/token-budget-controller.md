# Ticket 9 — Token Budget Controller

## Purpose

The controller is the provider-neutral budget boundary between visible Context
Packs and agent dispatch. It provides deterministic preflight estimates and
accounting guards. The Codex driver additionally enforces a per-node fresh
token safety limit because the CLI does not expose a portable output-token
flag.

The controller makes four limits explicit before a run:

1. planning tokens;
2. the base budget for every planned agent step;
3. retry count and retry-token pools;
4. handoff count and handoff-token pools.

## Budget presets

Empy provides three deterministic presets:

| Preset | Planning | Response per step | Retries | Handoffs | Reserve |
| --- | ---: | ---: | ---: | ---: | ---: |
| Economy | 3,000 | 2,500 | 1 × 1,200 | 1 × 500 | 1,000 |
| Standard | 5,000 | 5,000 | 2 × 2,000 | 2 × 800 | 2,000 |
| Extended | 8,000 | 8,000 | 3 × 3,000 | 3 × 1,200 | 4,000 |

The total local estimate is derived from the selected Context Pack, instruction
estimate, response allowance, retry pool, handoff pool, planning allowance and
reserve. A caller may also provide a smaller explicit `hard_total_limit` for
internal accounting; Empy rejects a budget that cannot fit inside it. The
current Codex CLI driver does not expose a portable maximum-output option, so
the actual provider total is measured after each node and shown separately.

## Token estimate and measured usage

Preflight planning uses a deterministic estimate and never blocks on a provider
tokenizer. ASCII content uses a conservative four-characters-per-token
estimate; non-ASCII content uses a two-characters-per-token estimate. The
Project Brain and bounded Context Packs reduce the amount sent to an agent.

After a Codex run, `TokenUsage` records input, output, cached-input, fresh
input, uncached total, total, provider, and source fields from structured
events. If a provider omits usage, Empy reports `not_reported` rather than
turning an estimate into a false exact value. The local benchmark and provider
usage are shown as separate signals.

## Locking

A budget starts as `draft`. The user can change the preset and recalculate it.
Selecting **Lock Run Limits** freezes the budget. A run state cannot be created
from an unlocked budget. Actual provider usage is evidence after the run, and
the driver applies a conservative fresh-token safety margin around the locked
node allocation; it does not silently rewrite the approved local estimate.

## Loop prevention

`apply_budget_usage` authorizes planning, agent, retry and handoff usage. It:

- rejects usage above the total budget;
- stops a run above the planning budget;
- stops a step above its agent allocation;
- denies retries after the configured retry count or retry-token pool;
- denies handoffs after the configured handoff count or handoff-token pool;
- records allowed and denied decisions in an immutable event trail.

Repeated retry or handoff requests after a limit do not charge more tokens and
remain denied. Therefore an infinite retry or handoff loop cannot be authorized
by the controller.

## Workspace persistence

Budgets are stored atomically at:

```text
~/.empy-studio/token-budgets.json
```

Each budget is keyed by its deterministic `budget_id` and can be restored by
Context Selection ID.

## Desktop flow

```text
Approved Plan
  → Context Packs
  → Token Budget panel
  → Select preset
  → Recalculate
  → Lock Run Limits
```

The panel exposes the total local estimate and the allocation for every planned step.
Ticket 9 does not dispatch agents. The locked budget becomes an input to Ticket
10, Agent Dispatcher.
