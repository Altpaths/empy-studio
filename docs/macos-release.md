# macOS Release Readiness

## Current supported path

Empy Studio's product UI is a local web desktop application. The macOS app
entry point packages that UI with PyInstaller and opens the authenticated local
browser session when the user launches the app from Finder. The app contains
the web assets, including the Empy logo, and does not require a terminal during
normal operation.

## Build stages

1. Build and test the Python wheel and source distribution.
2. Build an app bundle on a macOS runner matching the target architecture.
3. Smoke-test the bundle's `Contents/MacOS` executable and archive the app.
4. On an explicitly approved release run, sign with a Developer ID Application
   identity in an ephemeral keychain.
5. Submit for notarization, wait for an accepted result, and staple the ticket.
6. Verify the stapled artifact with Gatekeeper before publication.

Stages one through three run on every tag candidate. Stages four through six
run only from `workflow_dispatch` with `publish=true` and a protected
`release` environment containing the Apple credentials. Local builds never
pretend to have passed those gates.

An existing candidate can be finalized without moving its tag by running the
`Finalize macOS Release` workflow from `main`, selecting the candidate tag,
and setting `promote_latest=true`. That workflow downloads the candidate app,
signs and notarizes both architectures, rebuilds the manifest, replaces the
candidate assets, and marks the existing release as Latest only after the
notarization gate passes.

## Failure policy

- Missing PyInstaller fails the build.
- An architecture mismatch fails the build.
- A missing `.app` fails the build.
- A missing or invalid checksum fails the release gate.
- An unsigned or unnotarized artifact is a release candidate only, never a
  final v1 claim.
- A tag push cannot publish by itself; publication requires notarization
  evidence for both `arm64` and `x86_64` app archives.

The app build does not access, copy, or modify a user's project. The shipped
sample fixture is repository data, not application state.
