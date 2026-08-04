# Planner and Approval

## Roadmap position

Phase 3, Ticket 7 of `EMPY_PRODUCT_MASTER_PLAN.html`.

## User-visible workflow

```text
Open Project
→ Create Task
→ Save Task
→ Generate Plan
→ Review Plan
→ Approve Plan
```

## Plan preview

The user sees:

- overall risk;
- estimated number of affected files;
- suggested number of agent roles;
- estimated token requirement;
- likely project paths;
- ordered execution steps;
- step dependencies;
- suggested agent role for each step.

## Approval contract

A generated plan begins as `draft`. Approval checks the Task fingerprint and
then creates an immutable `approved` plan with an approval timestamp.

A Task changed after planning cannot approve the old plan. An approved plan
cannot be approved again or silently edited.

## Estimation boundary

Ticket 7 produces deterministic local estimates. It does not scan full project
contents, build final Context Packs, allocate actual token budgets, dispatch
agents, call Codex, or modify the target project.

Those responsibilities remain assigned to Tickets 8–11.
