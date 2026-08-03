# Changelog Validation

Ticket 6.2 validates the changelog before any release artifact or GitHub
release is created.

## Required format

```text
# Changelog

## [Unreleased]

### Added

- Pending change

## [1.2.0] - 2026-07-20

### Added

- Released change
```

## Validation rules

The validator checks:

- one `## [Unreleased]` section;
- release headings in `## [VERSION] - YYYY-MM-DD` format;
- valid Semantic Versions;
- valid calendar dates;
- no future dates;
- no duplicate versions;
- versions ordered newest to oldest;
- dates ordered newest to oldest;
- at least one `###` section for every released version;
- expected release version is the latest released version.

## Release integration

`validate_release_changelog()` binds changelog validation to the
`ReleaseVersion` selected by Ticket 6.1.

A failed validation blocks later release steps.

## Scope boundary

Ticket 6.2 does not:

- modify CHANGELOG.md;
- generate release notes;
- build artifacts;
- create Git tags;
- call GitHub;
- publish releases.
