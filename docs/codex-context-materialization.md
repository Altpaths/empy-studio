# Codex Context and AGENTS.md Materialization

Ticket 5.2 converts a planned Codex Run Manifest into a self-contained run
directory.

## Run layout

```text
<runs-root>/<run-id>/
  AGENTS.md
  prompt.md
  manifest.json
  context/
  evidence/
```

## AGENTS.md

The generated file contains:

- objective;
- acceptance criteria;
- allowed paths;
- forbidden paths;
- constraints;
- verification commands;
- operating rules.

It is generated from the stable Task Contract rather than handwritten for each
run.

## Prompt

The prompt restates the task ID, objective, required outcomes, final review,
verification, and reporting expectations.

## Context package

A bounded Context Builder output may be supplied as either a file or directory.
It is copied into the run directory so the execution record remains stable even
if the original Vault or workspace changes later.

## Safety and consistency

Materialization:

- accepts only `planned` runs;
- creates one isolated directory per run;
- sanitizes run IDs;
- refuses to overwrite an existing run;
- writes files atomically;
- removes partial run directories after failure;
- persists the prepared Run Manifest.

Codex execution is not performed in this stage.
