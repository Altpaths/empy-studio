# Distribution and Installer v1

Ticket 7 completes the standalone distribution pipeline for Empy Studio.

## Pipeline

```text
Distribution Build Config
  → Platform-specific Installer Generation
  → macOS/Linux shell installers
  → Windows PowerShell installer
  → macOS/Linux and Windows uninstallers
  → Distribution Manifest
  → GitHub Release asset verification
  → Direct download link map
```

## CLI

```bash
./.venv/bin/empy distribution build \
  --config distribution-build.json

./.venv/bin/empy distribution preflight \
  --minimum-python 3.10

./.venv/bin/empy distribution sync \
  --manifest dist/1.0.0/distribution-manifest.json \
  --selection latest-stable \
  --links-output dist/1.0.0/distribution-links.json

./.venv/bin/empy distribution inspect \
  --manifest dist/1.0.0/distribution-manifest.json
```

## Build configuration

```json
{
  "product": "Empy Studio",
  "version": "1.0.0",
  "repository": "Altpaths/empy-studio",
  "minimum_python": "3.10",
  "package_url": "https://github.com/Altpaths/empy-studio/releases/download/v1.0.0/empy_studio-1.0.0-py3-none-any.whl",
  "package_sha256": "<64-character-sha256>",
  "package_filename": "empy_studio-1.0.0-py3-none-any.whl",
  "output_dir": "dist/distribution",
  "entrypoint": "empy"
}
```

## Website integration

`distribution-links.json` contains direct GitHub Release asset URLs. Website
download buttons should point directly to these URLs so GitHub retains each
asset's download count.

## Safety

- no Clone is required;
- installers verify platform, Python, and SHA-256;
- installation uses isolated virtual environments;
- uninstallers remove only recorded installer-owned resources;
- no installer modifies shell profiles, Registry, or PATH automatically;
- no network access occurs during tests.
