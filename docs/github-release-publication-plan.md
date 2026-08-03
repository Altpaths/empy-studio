# GitHub Release Publication Plan

Ticket 8.8 prepares the exact publication request and website download map
without creating a GitHub Release.

## Inputs

```text
Release Candidate evidence
Controlled Tag Plan
Materialized Release Asset Plan
Release Notes
Repository identifier
```

## Publication request

The plan records:

- repository;
- exact tag;
- release name;
- exact target commit;
- release-notes path;
- draft state;
- prerelease state;
- GitHub latest-release strategy;
- every asset with SHA-256 and size.

## Release Candidate behavior

For `1.0.0-rc.1`:

```text
tag: v1.0.0-rc.1
prerelease: true
make_latest: false
```

For stable `1.0.0`:

```text
tag: v1.0.0
prerelease: false
make_latest: true
```

## Website links

The generated website map points directly to:

```text
https://github.com/OWNER/REPO/releases/download/TAG/ASSET
```

No proxy or redirect service is inserted. GitHub therefore preserves the
download counter for every Release asset.

## Publication blocker

The plan remains `blocked` unless:

- the Release Candidate decision is `ready`;
- materialized assets are present;
- the controlled tag plan is valid;
- every publication asset has SHA-256 and byte size.

## Scope boundary

Ticket 8.8 does not:

- create or push tags;
- call the GitHub API;
- create a GitHub Release;
- upload files;
- modify the website.

Ticket 8.9 performs the final verification workflow and controlled publication
handoff.
