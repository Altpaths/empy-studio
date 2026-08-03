# Empy Studio Plugin Package Manager

The Package Manager completes the lifecycle established by the Plugin SDK:

```text
Source
  → resolved .empy-plugin
  → verified artifact
  → transactional install
  → versioned Plugin Store
  → active version
  → Discovery
  → Loader
  → Hook Registry
  → Runtime
```

## Responsibilities

The Package Manager owns:

- local, file URL, HTTP, HTTPS, and GitHub Release source resolution;
- download limits and timeouts;
- SHA-256 calculation;
- transactional installation;
- versioned storage;
- active-version management;
- upgrade;
- rollback;
- removal;
- inventory listing;
- Store health inspection;
- transaction journals.

The Plugin SDK continues to own package format, manifest validation, package
integrity inspection, discovery, loading, and hook registration.

## Store layout

```text
<store>/
  inventory.json
  .store.lock
  transactions/
  packages/
    <plugin-id>/
      <version>/
  active/
    <plugin-id>.json
```

`inventory.json` is the authoritative state.

Every mutation uses:

- an exclusive Store lock;
- a transaction journal;
- staging or temporary trash;
- atomic inventory replacement;
- rollback after failure.

## Source resolution

Supported sources:

- local paths;
- `file://` URLs;
- direct HTTP and HTTPS URLs;
- GitHub Release assets.

Every source resolves to a local `.empy-plugin` candidate with:

- source type;
- local path;
- safe filename;
- SHA-256;
- byte size;
- source metadata.

## Installation

Installation performs:

1. source resolution;
2. package integrity and compatibility verification;
3. secure extraction;
4. staging;
5. atomic move into versioned storage;
6. inventory update;
7. active pointer update;
8. transaction commit.

Partial state is removed after failure.

## Upgrade and rollback

Upgrade installs a new version and retains previous versions.

Rollback activates an already-installed version without downloading or
reinstalling the package.

## Removal

An inactive version can be removed directly.

An active version requires a valid replacement version unless it is the final
installed version, in which case the complete plugin is removed.

## Health inspection

Store status checks:

- active version presence;
- active pointer presence and consistency;
- installed paths;
- manifests;
- payload directories.

The result is `healthy` or `degraded` with explicit issues.

## CLI

Install:

```bash
empy plugin install   --source example.empy-plugin   --store ~/.local/share/empy-studio/plugins   --empy-version 1.0.0
```

Upgrade:

```bash
empy plugin upgrade   --source example-2.0.0.empy-plugin   --store ~/.local/share/empy-studio/plugins   --empy-version 1.0.0
```

Rollback:

```bash
empy plugin rollback   --plugin-id example-plugin   --version 1.0.0   --store ~/.local/share/empy-studio/plugins
```

Remove one version:

```bash
empy plugin remove   --plugin-id example-plugin   --version 2.0.0   --replacement-version 1.0.0   --store ~/.local/share/empy-studio/plugins
```

Remove the complete plugin:

```bash
empy plugin remove   --plugin-id example-plugin   --store ~/.local/share/empy-studio/plugins
```

List:

```bash
empy plugin list   --store ~/.local/share/empy-studio/plugins
```

Status:

```bash
empy plugin status   --store ~/.local/share/empy-studio/plugins
```
