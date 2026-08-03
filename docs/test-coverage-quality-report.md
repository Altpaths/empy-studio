# Test Coverage and Quality Report

Ticket 8.5 creates one reproducible quality report for the Release Candidate.

## Commands

```text
python -m ruff check .
python -m mypy src
python -m coverage run --source src/empy_studio -m pytest tests -q
python -m coverage json -o <coverage.json>
```

The pipeline stops at the first failed command.

## Coverage gate

The coverage threshold is configurable and defaults to 80 percent. The report
records:

- covered lines;
- missing lines;
- total statements;
- exact coverage percentage;
- required threshold;
- pass or fail decision.

## Quality evidence

The evidence JSON contains:

- project SHA-256;
- every command and argument;
- stdout and stderr;
- return codes;
- failed command names;
- coverage totals;
- overall `passed` or `failed` status.

The report supports both Release Candidate gates:

```text
test_coverage
quality_gate
```

## Scope boundary

Ticket 8.5 does not automatically add or upgrade the `coverage` package,
modify source files, change the project version, create tags, or publish a
release.
