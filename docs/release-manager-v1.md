# Release Manager v1

Ticket 6 completes the controlled release pipeline for Empy Studio.

## Pipeline

```text
Semantic Version
  → Release Manifest
  → Changelog Validation
  → Deterministic Release Build
  → Artifact Index and SHA-256
  → Controlled Annotated Tag
  → Local Repository Guard
  → GitHub Actions CI Guard
  → GitHub Release Creation
  → Asset Upload and Verification
  → Publication Record
  ↘ Rollback on Partial Failure
```

## CLI

```bash
./.venv/bin/empy release validate \
  --manifest release-manifest.json \
  --changelog CHANGELOG.md

./.venv/bin/empy release build \
  --manifest release-manifest.json \
  --source-root . \
  --include src \
  --include README.md \
  --changelog CHANGELOG.md \
  --output-dir dist

./.venv/bin/empy release tag \
  --manifest dist/1.0.0/release-manifest.json \
  --repository-root . \
  --push

./.venv/bin/empy release publish \
  --manifest dist/1.0.0/release-manifest.json \
  --artifact-index dist/1.0.0/artifacts.json \
  --release-notes dist/1.0.0/RELEASE_NOTES.md \
  --repository-root . \
  --repository Altpaths/empy-studio \
  --rollback-dir dist/records

./.venv/bin/empy release inspect \
  --manifest dist/1.0.0/release-manifest.json \
  --artifact-index dist/1.0.0/artifacts.json
```

## Publication requirements

Publication is blocked unless:

- the Release Manifest is valid;
- Artifact Index matches the manifest;
- all artifacts still match size and SHA-256;
- the repository is on the release branch;
- the worktree is clean;
- the controlled tag points to HEAD;
- GitHub Actions CI for the same commit completed successfully.

## Failure handling

If GitHub creates the Release but asset publication fails:

- the incomplete Release is deleted;
- the tag reference is deleted;
- rollback metadata is saved;
- the original exception remains chained.

## Deliberate safeguards

- Tag push is explicit through `--push`.
- Tokens are read from an environment variable.
- Publishing is separate from building.
- Existing release output is not overwritten.
- No release is performed during tests.
