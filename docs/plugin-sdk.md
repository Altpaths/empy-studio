# Empy Studio Plugin SDK

Empy Studio uses one stable plugin lifecycle:

```text
Contract
  → verified .empy-plugin artifact
  → installed package directory
  → metadata-only discovery
  → explicit isolated loading
  → atomic hook registration
  → runtime consumption
```

## Architectural boundary

The Plugin SDK owns:

- plugin contracts;
- manifest validation;
- compatibility checks;
- `.empy-plugin` artifact structure;
- SHA-256 integrity verification;
- metadata-only discovery;
- isolated loading;
- hook registration.

The Plugin Package Manager, implemented in Ticket 4, owns:

- source resolution;
- download;
- installation;
- upgrade;
- removal;
- rollback;
- registry access.

The Multi-Agent Runtime consumes registered agents and adapters. It does not
download or install plugins and does not need to know where a plugin originated.

## Artifact format

A distributable plugin uses the `.empy-plugin` suffix and contains:

```text
plugin.json
RECORD.sha256.json
SIGNATURE.json
payload/
  module.py
```

`SIGNATURE.json` is optional metadata at the SDK layer. Cryptographic trust
policy and key verification are enforced by release and package-management
policy.

Every payload file must be listed in `RECORD.sha256.json`. Package inspection
rejects:

- unsafe archive paths;
- missing recorded files;
- file-size mismatches;
- SHA-256 mismatches;
- unrecorded payload files;
- missing entrypoint modules;
- incompatible Empy Studio versions.

## Manifest

A manifest declares:

- stable plugin ID;
- display name;
- semantic version;
- required Empy Studio version;
- entrypoint;
- supported hooks;
- capabilities;
- description.

Example:

```json
{
  "plugin_id": "example-plugin",
  "name": "Empy Example Plugin",
  "version": "1.0.0",
  "empy_requires": ">=1.0.0",
  "entrypoint": "example_plugin:Plugin",
  "hooks": [
    "agent",
    "adapter",
    "validator",
    "context_provider"
  ],
  "capabilities": [
    "example"
  ]
}
```

## Discovery

Discovery reads only `plugin.json`. It never imports or executes plugin code.

It reports each invalid plugin independently, including:

- malformed JSON;
- missing required fields;
- invalid field types;
- incompatible versions;
- duplicate plugin IDs;
- missing or invalid discovery roots.

## Loading

Loading is explicit and occurs only after discovery and compatibility checks.

The loader:

- resolves the declared entrypoint;
- imports the plugin under an isolated module name;
- supports class and object entrypoints;
- removes failed imports from `sys.modules`;
- prevents module-name collisions between plugins.

## Hook registry

Version 1 supports four stable hook categories:

- agent;
- adapter;
- validator;
- context provider.

Registration is atomic. If any declared hook fails validation, no partial
registration is retained.

Duplicate plugin registration and duplicate adapter IDs are rejected.

## CLI

Discover installed plugins without importing code:

```bash
empy plugin discover   --root ~/.local/share/empy-studio/plugins   --empy-version 1.0.0
```

Inspect and verify an artifact:

```bash
empy plugin inspect   --package example-plugin.empy-plugin   --empy-version 1.0.0
```

Validate one installed plugin directory:

```bash
empy plugin validate   --plugin-root ~/.local/share/empy-studio/plugins/example-plugin   --empy-version 1.0.0
```

## Reference implementation

`examples/plugins/example_plugin` implements all four hooks and is covered by
the automated test suite.
