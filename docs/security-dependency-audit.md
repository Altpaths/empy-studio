# Security Review and Dependency Audit

Ticket 8.4 creates offline, reproducible security evidence for the Release
Candidate.

## Dependency audit

The audit records:

- declared runtime dependencies;
- optional dependency groups;
- installed package inventory;
- `pip check` consistency results;
- deterministic project digest.

The audit does not query external vulnerability databases. Network-backed
vulnerability checks can be added as separate evidence during the final
release process, but they are not silently required by this offline gate.

## Source review

Python source is parsed with `ast` and checked for high-risk constructs:

- `eval()` and `exec()`;
- `pickle.load()` and `pickle.loads()`;
- subprocess APIs using `shell=True`;
- syntax errors in shipped source.

## Secret scan

Text files are checked for:

- AWS access keys;
- GitHub tokens;
- private-key blocks;
- long hard-coded token, secret, password, or API-key assignments.

Potential secrets and high-risk source patterns block the audit.

## Evidence

The JSON report contains:

- dependency inventory;
- command results;
- findings with severity, path, and line;
- blocking-finding count;
- project SHA-256;
- overall `passed` or `failed` status.

This evidence supports the `security_review` and `dependency_audit` Release
Candidate gates.

## Scope boundary

Ticket 8.4 does not change dependencies, access the network, update lock files,
change versions, tag, or publish a release.
