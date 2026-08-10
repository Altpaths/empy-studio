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

Independent tasks in the same dependency wave are executed in bounded batches
up to `max_workers` (four by default). The runtime records each batch, start and
finish timestamps, observed parallelism, agent selection, retry attempts, and
per-task evidence. Scheduler capacity is applied before a batch is started, so
an agent is never assigned more concurrent work than its declared capacity.
Handoffs and memory updates are committed in deterministic task order after a
batch completes; dependents never start before the whole dependency wave is
resolved.

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
