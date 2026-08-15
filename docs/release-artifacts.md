# Release Artifacts

Ticket 18 makes release output inspectable before publication. The build is
local and network-free after dependencies are installed; it does not create a
Git tag, call GitHub, or upload anything.

## Build and verify package assets

```bash
python -m pip install ".[dev]"
python scripts/build_release_assets.py --output build/release-assets
python scripts/verify_release_assets.py build/release-assets/release-assets.json
python scripts/smoke_unix_installer.py \
  --installer build/release-assets/install-linux-x86_64.sh \
  --package build/release-assets/*.whl \
  --target linux-x86_64
```

The output contains the wheel, source distribution, generated platform
installers, distribution manifest, `RELEASE_NOTES.md`, `SHA256SUMS`, and
`release-assets.json`. The verifier checks every recorded byte size and
SHA-256 value, rejects contaminated wheel/app archives, then checks the
installer assets against the distribution manifest. The installer smoke test
uses a local wheel in a temporary HOME and executes the final relocated
wrapper.

On macOS, the Finder app candidate is built separately and can be added to the
same release manifest:

```bash
python scripts/build_macos_app.py \
  --output "build/app/Empy Studio.app" \
  --architecture arm64 \
  --clean-workspace
ditto -c -k --norsrc --noextattr --noqtn --keepParent \
  "build/app/Empy Studio.app" build/app/empy-studio-macos-arm64.zip
```

This candidate is not called notarized until the Apple signing workflow has
accepted it. Users can still approve an unsigned local candidate through
Privacy & Security → Open Anyway.

## Build the macOS app

The Finder-launchable app is built only on macOS with the release extra:

```bash
python -m pip install ".[release]"
python scripts/build_macos_app.py \
  --output "build/Empy Studio.app" \
  --architecture auto
```

`auto`, `arm64`, `x86_64`, and `universal2` are accepted. The command fails if
PyInstaller is unavailable or if it does not produce a real `.app` bundle; a
shell installer is never mislabeled as a desktop app.

## Release gates

The GitHub release workflow runs the Python matrix, builds and verifies package
assets, smoke-tests the Linux installer, and builds macOS arm64 and x86_64 app
bundles. A tag push creates candidate workflow artifacts only. Publication is
available through `workflow_dispatch` on the selected tag with `publish=true`
and a protected `release` environment. That path imports the Developer ID
certificate, signs, notarizes, staples, runs Gatekeeper checks, records
per-architecture evidence, and requires:

```bash
python scripts/verify_release_assets.py \
  --require-notarized release-assets/release-assets.json
```

Without those Apple credentials and checks, the workflow cannot publish a
public release. This is deliberate: unsigned or unnotarized artifacts remain
release candidates and are never called final v1.

No secrets, `.empy` state, virtual environments, caches, or user project files
belong in release artifacts.
