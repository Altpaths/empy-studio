# Version Alignment, Release Assets, and Tag Plan

Ticket 8.7 prepares the Release Candidate version and publication inputs
without creating a Git tag or GitHub Release.

## Version alignment

The authoritative candidate version is:

```text
1.0.0-rc.1
```

The stable target remains:

```text
1.0.0
```

Every configured version source must match the candidate version. Optional
version sources may be absent, but an existing optional source must match.

## Release assets

The default Release Candidate plan expects:

```text
Python wheel
Source distribution
Distribution Manifest
Artifact Index
Release Candidate evidence
```

Asset SHA-256 and byte size are recorded only after files exist. Missing
required assets keep the plan blocked.

## Tag preparation

The candidate tag is:

```text
v1.0.0-rc.1
```

The stable tag is reserved:

```text
v1.0.0
```

Ticket 8.7 permits planning the annotated candidate tag but explicitly blocks
creation of the stable tag during RC preparation.

## Scope boundary

Ticket 8.7 does not:

- rewrite project version files automatically;
- build the Python package;
- create or push a Git tag;
- publish a GitHub Release;
- upload release assets.

Those operations occur only after the full Release Candidate quality gate is
green.
