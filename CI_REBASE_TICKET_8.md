# Ticket 8 CI Rebase

This checkpoint contains Ticket 8 (Context Selector) rebased on the CI fixes
applied after Ticket 7 was pushed to `main`.

Included corrections:

- strict `mypy` decoding for persisted task, plan, and project data;
- typed Tkinter callbacks and `ExecutionPlan | None` state;
- Python 3.10–3.12 TOML compatibility;
- Ruff-compliant exception typing;
- Ticket 8 Context Selector source, tests, documentation, and desktop UI.

Validation performed in the build environment:

- `407 passed`;
- Python source compilation passed;
- ZIP integrity passed.

Run Ruff, mypy, and pytest again in the target repository before committing.
