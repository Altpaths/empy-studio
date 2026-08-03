# Multi-Agent Runtime

The runtime executes a dependency-aware graph of bounded tasks through registered
agent adapters. It does not contain or impersonate a language model.

## Design boundary

Empy Studio owns:

- task contracts;
- capability matching;
- dependency waves;
- retries and timeouts;
- handoffs;
- agent memory;
- execution state;
- evidence and failure propagation.

An external host owns model inference and tool use. Codex, Claude Code, a local
script, or another system connects through an adapter.

## Manifest execution

```bash
empy runtime run \
  --manifest examples/runtime.json \
  --output-root .empy-runtime
```

The runtime writes:

```text
.empy-runtime/
├── runs/<run-id>.json
└── memory/<agent-id>.json
```

## Adapter contract

A command adapter receives two substituted arguments:

- `{input}`: JSON file containing task, context, memory, and handoffs;
- `{output}`: file the adapter must create using the `AgentOutput` schema.

A valid output has:

```json
{
  "status": "passed",
  "result": {},
  "evidence": [],
  "memory_updates": {}
}
```

Timeout is enforced at the subprocess boundary. Failed dependencies block their
dependents by default.
