# Ticket 12 — Driver Abstraction & Settings

## Purpose

Ticket 12 removes hard provider selection from the product workflow and makes AI providers replaceable through a provider-neutral registry and persisted desktop settings.

The product core defines only provider-independent contracts and settings models. Provider packages depend on the core; the core never imports Codex, Claude, Gemini, or the driver package.

## Delivered architecture

```text
Empy Core
  ├─ DriverCapabilities
  ├─ DriverConfiguration
  ├─ DriverSettings
  ├─ DriverInspection
  └─ AIDriver protocol
        ↑
Driver Registry / Manager
  ├─ Codex factory (implemented)
  ├─ Claude slot (unavailable)
  └─ Gemini slot (unavailable)
        ↑
Desktop Driver Settings
  ├─ default provider
  ├─ enabled state
  ├─ executable path
  ├─ credential mode metadata
  ├─ capability matrix
  └─ live availability inspection
```

## Settings persistence

Driver configuration is stored in `~/.empy-studio/driver-settings.json` by default. The file stores provider identity, enabled state, executable path, credential mode, and environment-variable name when applicable.

Credential secrets, API keys, access tokens, and login material are never persisted by this adapter. Codex authentication remains managed by Codex CLI login. Future providers may use their own CLI or environment-based credential mechanism.

## Capability matrix

The matrix reports only capabilities executable in the current build.

- **Codex:** implemented; code editing, verification, streaming, cancellation.
- **Claude:** provider slot registered; execution unavailable in Ticket 12.
- **Gemini:** provider slot registered; execution unavailable in Ticket 12.

Unavailable providers are visible instead of being presented as working integrations.

## Driver selection

The desktop settings page can choose an enabled provider as the default. `DriverManager` resolves the selected provider through `DriverRegistry`; callers do not instantiate Codex directly.

The current graph runtime remains available for the implemented Codex driver. Selecting an unavailable provider disables execution and displays its remediation state. Claude and Gemini runtime implementation is intentionally outside Ticket 12.

## Definition of Done evidence

- Core source contains no Codex or `empy_studio.drivers` imports.
- Driver selection is replaceable through registry factories and persisted settings.
- Missing, unauthenticated, disabled, and unimplemented states are represented explicitly.
- Desktop Settings displays provider status and capability matrix.
- Automated tests cover registry selection, swapping, unavailable providers, settings persistence, and architecture boundaries.

## Explicit exclusions

Ticket 12 does not implement:

- Claude execution;
- Gemini execution;
- multi-provider parallel runs;
- patch synchronization;
- conflict resolution;
- verification pipeline UI.

Those items remain in later roadmap tickets.
