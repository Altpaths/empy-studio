# Final Release Candidate Verification and Handoff

Ticket 8.9 closes the Release Candidate workflow without performing an
uncontrolled publication.

## Evidence aggregation

The finalizer consumes:

```text
clean-environment.json
real-project-scenario.json
security-audit.json
quality-evidence.json
documentation-evidence.json
version-alignment.json
release-assets.json
publication-plan.json
```

Each evidence file updates its mapped Release Candidate gate.

## Download verification

Every website download URL must:

- point directly to GitHub;
- use the `/releases/download/` asset path;
- pass the configured link verifier.

A failed platform link blocks the Release Candidate.

## Final outputs

```text
release-candidate-final.json
publication-handoff.json
final-release-report.json
```

The publication handoff contains the exact repository, release tag, target
commit, release notes, assets, website links, and commands required for the
controlled publication step.

## Safety boundary

Ticket 8.9 does not execute the commands contained in the handoff.

It does not:

- create or push a Git tag;
- call GitHub;
- create a Release;
- upload assets;
- change website files.

The handoff becomes executable only after the final report is `ready`, the
working tree is committed, the branch CI is green, and the exact commit SHA is
confirmed.

## Stable release

The Release Candidate uses:

```text
version: 1.0.0-rc.1
tag: v1.0.0-rc.1
```

The stable `1.0.0` release and `v1.0.0` tag remain blocked until the candidate
has been installed, exercised, uninstalled, and accepted on the supported
clean systems.
