# Release Candidate Contract

Ticket 8.1 defines the authoritative readiness contract for Empy Studio
`1.0.0-rc.1` and the stable target `1.0.0`.

## Required gates

```text
clean_environment
clean_install
real_project_scenario
security_review
dependency_audit
test_coverage
quality_gate
documentation_en
documentation_fa
example_project
version_alignment
release_assets
download_verification
```

Every gate is required. A required gate cannot be waived.

## Decisions

```text
blocked
ready
```

A Release Candidate is `ready` only when every required gate has status
`passed`. Pending or failed gates block publication.

## Evidence

Each gate may contain one or more evidence records:

- evidence kind;
- repository-relative or controlled external path;
- optional SHA-256;
- optional notes.

Evidence files are created in later Ticket 8 sections. Ticket 8.1 only
defines and validates the contract.

## Version rules

- candidate version must be an `rc.N` prerelease;
- target version must be stable;
- candidate and target must share the same major, minor, and patch;
- the intended branch is `release/v1.0.0-rc`.

## Scope boundary

Ticket 8.1 does not:

- rebuild the environment;
- install the package;
- execute a real project;
- run a security audit;
- change project versions;
- create a Git tag;
- publish a GitHub Release.
