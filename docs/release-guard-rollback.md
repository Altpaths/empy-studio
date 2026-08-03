# Release Guard and Rollback

Ticket 6.6 prevents publication unless the local repository, release tag,
artifacts, and GitHub Actions state are valid.

## Guard checks

Before publication:

- current branch must be the configured release branch;
- Git worktree must be clean;
- HEAD commit must resolve;
- the controlled release tag must point to HEAD;
- Artifact Index verification must pass;
- Artifact Index must match Release Manifest;
- the latest completed CI workflow for the release commit must conclude with
  `success`.

A failed check blocks publication.

## Rollback metadata

When publication fails after a GitHub Release has already been created, the
rollback controller can:

- delete the GitHub Release;
- delete the release tag reference;
- record release ID;
- record tag and version;
- record commit SHA;
- record previous version and tag;
- record the rollback reason;
- record affected artifact names;
- persist `rollback-<tag>.json`.

## Scope boundary

Ticket 6.6 does not perform the complete end-to-end release pipeline. That
final orchestration, CLI integration, documentation, and full quality gate are
part of Ticket 6.7.
