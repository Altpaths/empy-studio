# Real Project Scenario Evidence

Ticket 8.3 executes Empy Studio against a controlled, realistic project
scenario and records evidence suitable for the Release Candidate checklist.

## Scenario contents

The example scenario contains:

- `AGENTS.md`;
- a Task Contract;
- a runtime manifest;
- expected output files;
- deterministic project and scenario digests.

## Execution

```text
Copy current project without local caches
  → Copy controlled example project
  → Execute `empy runtime run`
  → Verify required outputs
  → Persist command evidence and digests
```

The scenario runs without Codex or network access. It validates the host-neutral
runtime and evidence path that remains available when an external coding model
is unavailable.

## Evidence

The report includes:

- source-project SHA-256;
- scenario SHA-256;
- executed command;
- return code;
- stdout and stderr;
- verified output list;
- overall `passed` or `failed` status.

This evidence supports the `real_project_scenario` Release Candidate gate.

## Scope boundary

Ticket 8.3 does not perform security review, dependency audit, coverage
measurement, version changes, tagging, or publication.
