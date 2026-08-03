# Empy Studio 1.0.0-rc.1

This Release Candidate validates the complete version 1 architecture before
the stable `v1.0.0` publication.

## Included

- task contracts and evidence-oriented orchestration;
- host-neutral runtime;
- plugin SDK and package manager;
- Codex workflow adapter with session continuation;
- controlled Release Manager;
- macOS, Linux, and Windows distribution pipeline;
- clean uninstallers;
- Release Candidate gates and evidence.

## Release Candidate purpose

This build is intended for final clean-environment, installation, security,
coverage, documentation, and real-project validation.

It is not the final stable release.

## Required validation before stable release

- all Release Candidate gates must pass;
- CI must pass for the exact tagged commit;
- all release assets must match the Artifact Index;
- installer downloads and uninstalls must be tested;
- GitHub download links must resolve to Release assets;
- no critical or high-severity security finding may remain.

## Upgrade path

The stable release will use version `1.0.0` and tag `v1.0.0` only after this
candidate is accepted.
