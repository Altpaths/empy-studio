# Release Builder

Ticket 6.4 produces a complete local release directory without creating Git
tags or calling GitHub.

## Output layout

```text
dist/<version>/
  empy-studio-<version>.zip
  empy-studio-<version>.zip.sha256
  RELEASE_NOTES.md
  release-manifest.json
  artifacts.json
```

## Build pipeline

```text
Release Manifest
  → Changelog Validation
  → Release Notes Extraction
  → Deterministic ZIP
  → SHA-256 Sidecar
  → Artifact Index
  → Final Release Manifest
```

## Deterministic archive

The ZIP builder:

- includes only explicitly selected files and directories;
- orders members by relative path;
- normalizes timestamps;
- normalizes file permissions;
- uses a fixed compression level.

Identical input produces identical archive bytes.

## Transactional output

The builder writes into a temporary staging directory and atomically moves the
completed release into `dist/<version>`.

Existing release directories are never overwritten.

## Scope boundary

Ticket 6.4 does not:

- create Git tags;
- inspect CI;
- call GitHub;
- upload assets;
- select the latest release;
- publish or roll back a release.
