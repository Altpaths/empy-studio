# Experimental OmniRoute connection and adaptive token economy (0.1.55)

Choose **Model connection: direct or OmniRoute** on the project screen. Direct
keeps the existing Codex account route; its normal account usage applies.
OmniRoute is an explicit alternative, not a fallback from Direct.

The experimental route accepts literal loopback HTTP addresses ending in `/v1`
(default `http://127.0.0.1:20129/v1`). Model IDs are explicit: `oc/north-mini-code-free`,
`oc/big-pickle`, or a local `ollama/...` / `lmstudio/...` model advertised by the
gateway. `auto` and `default` are rejected. Paid model IDs require the explicit
`allow_paid` opt-in in the UI or route setting; there is never an automatic
fallback or remapping. Availability and provider terms can change; an
advertised catalog entry is not proof that inference works.

## Adaptive provider-call economy

Provider execution has a fixed harness cost. For low/medium-risk tickets that
touch three or more domains, the planner uses one bounded coordinator node while
retaining the selected-file ownership contract. High-risk tickets and tickets
that explicitly request separate specialist agents retain specialist fan-out.
This is a planning optimization, not a claim about hidden provider reasoning
tokens. Run the offline benchmark before comparing real providers:

```sh
PYTHONPATH=src python scripts/benchmark_token_efficiency.py \
  --evidence-dir /path/to/new-token-evidence
```

The benchmark makes zero provider calls and reports planned reductions only.
Real quality and cost comparisons still require the same fixture, a working
provider, and usage events from that provider.

## Persistence ownership safety

When a backend ticket asks to store, persist, record, or keep history, Empy
marks matching `database/`, `migrations/`, `schema/`, and `.sql` files as the
bounded implementation surface for that backend node. A related schema file
stays read-only for tickets that do not request persistence. The runtime
ownership audit remains the final guard and still rejects any genuinely
unowned edit.

A dedicated API-key environment variable NAME can be configured if the gateway
requires authentication. Never enter a key value. GUI launches must inherit that
variable to use it. Shared OpenAI credentials are stripped and Codex uses a separate
empty CODEX_HOME for this route. No account login/configuration is rewritten.

Run your trusted OmniRoute instance on the selected port and explicitly disable
paid remapping/fallback server-side. Client model allowlisting does not control
the gateway's upstream configuration. The local catalog refuses redirects;
Codex's Responses transport still trusts the local gateway. This is not a proxy
security audit or a guarantee that arbitrary gateway configuration is free.

## Tests and limits

Status polling uses a cache; Refresh checks CLI capabilities and the gateway's
model catalog, and each actual node rechecks before execution. Routing is locked
during startup, execution and an active recovery gap. Run reports retain the route
used. Corrupt saved route settings fail closed until explicitly corrected.

The OmniRoute route disables Codex HTTP/stream reconnect retries and web search.
Empy's existing economy policy and internal token guard remain; a gateway does
not remove the 41,616-token failure condition reported for the earlier ticket.
No lower real cost or universal successful repair is claimed.

Tests on 2026-09-12: both free chat routes returned 403; the actual Responses
coding route reported unsupported model / 401 and timed out after reconnects.
No local Ollama service was available. Those were observed failures, not successes.
The final rebuilt route is tested separately with retries disabled.

To repeat a bounded synthetic coding probe (never Direct):

```sh
PYTHONPATH=src python scripts/compare_omniroute.py \
  --base-url http://127.0.0.1:20129/v1 \
  --model oc/north-mini-code-free \
  --evidence-dir /path/to/new-evidence-folder
```

This uses a fresh synthetic calc.py, a 45-second deadline and a 12,000 fresh-token
local guard. Generated code is checked by AST without execution. Missing usage
and billing remain unknown, not zero. Use only a trusted isolated gateway with
no paid remapping or account fallback. Real model quality comparison requires a
working free/local model; a mock gateway cannot establish that result.
