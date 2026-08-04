# Agent Dispatcher — Ticket 10

## Purpose

The Agent Dispatcher converts an approved execution plan, bounded context
selection, and locked token budget into a deterministic **Agent Run Graph**.
It does not call Codex or another provider. Provider execution begins in
Ticket 11.

## Preconditions

The dispatcher rejects construction unless:

- the execution plan is approved;
- the context selection belongs to that plan;
- the token budget belongs to that context selection;
- the token budget is locked;
- every plan step has one context pack and one token allocation.

## Agent registry and capability matching

The provider-neutral registry contains enabled definitions for discovery,
frontend, backend, security, quality, and release roles. Every definition has
an explicit capability set and bounded-execution capability.

For each approved plan step, the dispatcher:

1. derives required capabilities from the planned role;
2. considers only enabled agents with that exact role;
3. rejects agents that do not satisfy every required capability;
4. selects deterministically by priority, capability excess, and agent ID.

Agents unrelated to the approved plan remain visible in the registry snapshot
but receive no run node.

## File ownership

Every context path receives exactly one ownership record.

- Discovery and Quality are read-only.
- Frontend, Backend, Security, and Release may receive write ownership.
- A path can have at most one writer.
- Competing writers are resolved deterministically using ownership-pattern
  specificity, context relevance score, and approved plan order.
- Other agents that need the same path are recorded as readers.
- Protected exclusions from the Context Selector never enter a node or an
  ownership record.

This is a pre-execution ownership contract. Ticket 13 will enforce ownership
while applying patches and resolving conflicts.

## Sequencing

Plan dependencies are converted to node dependencies and topological execution
waves. Graph validation rejects unknown dependencies, self-dependencies,
cycles, duplicate nodes, and any dependency placed in the same or a later wave.

## Desktop and persistence

A locked Token Budget panel can build or reopen the Agent Run Graph. The UI
shows:

- assigned agents and run nodes;
- execution waves and dependencies;
- context-pack and token-limit binding;
- owned and read-only files;
- protected-path count.

Graphs are persisted in `agent-run-graphs.json` under the local Empy workspace.

## Scope boundary

Included in Ticket 10:

- agent registry;
- role and capability matching;
- single-writer file ownership;
- dependency sequencing;
- persistent Agent Run Graph;
- desktop graph preview.

Not included:

- AI provider invocation;
- Codex session execution;
- streaming logs or cancellation;
- patch application and conflict resolution.
