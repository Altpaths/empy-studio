# Artifact Index

Ticket 6.3 creates the authoritative index of release assets before packaging
or publication.

## Output

The index is written as `artifacts.json` and records:

- schema version;
- product;
- release version;
- controlled tag;
- artifact root;
- public asset name;
- relative file path;
- SHA-256;
- byte size;
- media type;
- total artifact size;
- release metadata.

## Determinism

Entries are sorted by public asset name. Absolute machine-specific paths are
not stored in entries.

## Safety

The indexer:

- rejects files outside the declared artifact root;
- rejects missing files;
- rejects duplicate public names;
- rejects duplicate relative paths;
- calculates SHA-256 from file contents;
- verifies indexed files before later release stages;
- detects missing, resized, or tampered artifacts.

## Manifest integration

`ArtifactIndex.apply_to_manifest()` creates a validated Release Manifest whose
artifact records match the index.

## Scope boundary

Ticket 6.3 does not:

- build ZIP packages;
- generate release notes;
- create Git tags;
- call GitHub;
- upload assets;
- choose the latest release.
