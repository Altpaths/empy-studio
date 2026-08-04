# Task Intake: Templates and Custom Tasks

## Roadmap position

Phase 2, Ticket 6 of `EMPY_PRODUCT_MASTER_PLAN.html`.

## User-visible value

Inside Project Home, the user can click **Create Task** and choose:

- Fix a bug
- Add a feature
- Improve UI
- Audit project
- Prepare release
- Custom task

Every prepared task remains editable.

## Task fields

- Task title
- Objective
- Requirements
- Constraints
- Definition of Done

The user writes normal text. Empy converts multiline text into a structured
`ProductTask`; the user never writes JSON.

## Preview and persistence

Before saving, Empy displays a Task Preview. Saved tasks are marked
`ready_for_planning` and appear in Project Home.

## Scope boundary

Ticket 6 does not create an execution plan, select agents, build context,
estimate tokens, execute AI drivers, verify changes, or review diffs.
Planning begins in Ticket 7.
