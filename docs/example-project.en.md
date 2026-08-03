# Example project

This example demonstrates the smallest complete Empy Studio workflow for v1.

## Structure

```text
examples/v1-sample-project/
  AGENTS.md
  README.md
  task-contract.json
  runtime-manifest.json
  input/
    customer-request.md
```

`AGENTS.md` defines operating rules. The Task Contract defines the objective,
constraints, and acceptance criteria. The runtime manifest binds the task to
expected output and evidence.

## Run

From the example directory:

```bash
empy runtime run \
  --manifest runtime-manifest.json \
  --output-root outputs
```

The scenario is deliberately local and does not require network access.

## Expected evidence

A successful run should preserve:

```text
outputs/result.json
outputs/evidence.json
```

The evidence must identify the task, source inputs, executed command, output
paths, and completion status.

## Review

Do not accept the result merely because a command returned zero. Confirm that
the declared acceptance criteria and expected output files are satisfied.
