# Release Versioning and Manifest

Ticket 6.1 defines the stable version and release-manifest contracts used by
the remaining Release Manager pipeline.

## Semantic versions

`ReleaseVersion` implements Semantic Versioning precedence:

```text
MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
```

Supported operations:

- strict parsing;
- normalized serialization;
- semantic precedence comparison;
- major, minor, and patch increments;
- prerelease construction;
- metadata removal.

Build metadata does not affect precedence.

## Release manifest

`ReleaseManifest` is the authoritative contract between release validation,
artifact indexing, package building, GitHub publishing, and rollback metadata.

The manifest records:

- schema version;
- product;
- semantic version;
- controlled `v<version>` tag;
- stable or prerelease channel;
- release name;
- release-notes path;
- changelog path;
- artifacts;
- previous version;
- extensible metadata.

## Artifact contract

Every release artifact records:

- public asset name;
- local path;
- SHA-256;
- size;
- media type.

Artifact names must be unique.

## Scope boundary

Ticket 6.1 does not:

- inspect CHANGELOG contents;
- build release archives;
- create Git tags;
- call GitHub;
- publish assets;
- inspect CI status.

Those responsibilities remain in Tickets 6.2 through 6.7.
