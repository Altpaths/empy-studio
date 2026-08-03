# GitHub Release Publisher

Ticket 6.5 publishes a locally built release to GitHub Releases.

## Pipeline

```text
Validated Release Manifest
  → Verified Artifact Index
  → Create GitHub Release
  → Upload Binary Assets
  → List Remote Assets
  → Verify Name, Size, State, and Digest
```

## Authentication

The publisher accepts a token explicitly or reads `GITHUB_TOKEN` through
`token_from_environment()`.

Tokens are never written into:

- Release Manifest;
- Artifact Index;
- logs;
- result objects;
- command evidence.

The token requires repository Contents write permission for release and asset
management.

## API

The publisher uses the versioned GitHub REST API and sends:

```text
Accept: application/vnd.github+json
Authorization: Bearer <token>
X-GitHub-Api-Version: 2026-03-10
```

Release assets are uploaded as raw binary content using the `upload_url`
returned by GitHub.

## Latest strategy

Supported policies:

- `auto`: stable releases become latest; prereleases do not;
- `always`: always request latest;
- `never`: never request latest;
- `legacy`: use GitHub's legacy semantic/date behavior.

## Verification

After uploading, the publisher lists remote assets and verifies:

- asset name;
- byte size;
- `uploaded` state;
- SHA-256 digest when GitHub provides it.

## Scope boundary

Ticket 6.5 does not:

- check CI state;
- create or verify Git tags locally;
- delete failed releases;
- record rollback metadata;
- recover from partial publication.

Those controls belong to Ticket 6.6.
