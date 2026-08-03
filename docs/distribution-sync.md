# GitHub Release Distribution Sync

Ticket 7.6 connects generated installer assets to GitHub Releases without
proxying downloads through another server.

## Release selection

Supported strategies:

```text
latest-stable
latest-prerelease
tag
```

`latest-stable` uses GitHub's latest release endpoint. Prereleases are selected
explicitly and drafts are always rejected.

## Asset verification

Every remote asset is matched against the Distribution Manifest by:

- asset name;
- byte size;
- media type;
- uploaded state;
- SHA-256 digest when GitHub provides one.

A missing or inconsistent installer asset blocks link generation.

## Website link map

The sync produces `distribution-links.json` containing one direct
`browser_download_url` per platform target.

The website can use these URLs directly. Downloads therefore go to GitHub
Release assets and remain visible in each asset's GitHub download counter.

## Scope boundary

Ticket 7.6 does not modify the website, download installers, install software,
or publish GitHub Releases. Ticket 7.7 completes CLI integration, artifact
generation, documentation, and the end-to-end quality gate.
