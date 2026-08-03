# Capability Graph and Agent Scheduling

The scheduler translates a task's declared needs into canonical capabilities,
expands aliases, implications, and prerequisites, then ranks eligible agents.

## Why capability-first

Tasks request capabilities rather than named vendors or fixed personas. This
keeps Empy Studio independent of Codex, Claude, Gemini, local agents, and future
providers.

## Scheduling inputs

Each agent may have:

- capabilities;
- capacity;
- priority;
- expected cost;
- reliability.

The scheduler excludes agents that lack required capabilities or available
capacity. It records the winning score and human-readable reasons in the run
state.

## CLI

```bash
empy capabilities plan \
  --manifest examples/capabilities.json
```

## Runtime integration

`MultiAgentRuntime` accepts an optional `AgentScheduler`. When supplied, every
task records the complete scheduling decision beside its execution state.
