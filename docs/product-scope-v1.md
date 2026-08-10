# Empy Studio Product Scope — Version 1

## Product objective

Empy Studio v1 is an independent local-first product for macOS, Linux, and Windows. It lets a user select an existing software project, describe a task in natural language, review the execution plan, run bounded AI agents through replaceable drivers, verify the resulting changes, and accept or revert them without using the terminal for normal product operation.

## Required user journey

```text
Download → Install → Open → Choose Project → Write Request
→ Review Plan → Run → Review Changes and Tests → Accept or Revert
```

## In scope for v1

1. One Python/Web Desktop product path on supported operating systems, with optional native packaging.
2. Browser-based folder/ZIP selection and recent projects; native pickers are optional host integrations.
3. Prepared task templates and custom natural-language tasks.
4. Task-contract generation without user-authored JSON.
5. Execution-plan preview, editing, approval, and cancellation.
6. Bounded context selection and visible token budgets.
7. Automatic agent selection, sequencing, and file ownership.
8. A production Codex driver behind a provider-neutral interface.
9. Patch synchronization and conflict detection.
10. Verification results and evidence visible in the desktop UI.
11. Changed-file and diff review with accept and revert.
12. A successful Kit4Kids acceptance run.
13. Downloadable Python/wheel and platform installer assets, plus native packages where a platform build is available.

## Explicitly out of scope for v1

- A plugin marketplace user interface.
- Mobile applications.
- A hosted SaaS account system.
- Team collaboration or a remote coordination server.
- Autonomous commit, push, merge, or publication without explicit approval.
- Production support for multiple AI providers before the Codex acceptance path works.
- Broad refactoring of working core modules without direct product necessity.

## Product constraints

- Empy remains the product; Codex and later providers remain replaceable drivers.
- The desktop application must not require terminal commands for routine use.
- The user must not create JSON manifests or manually select agents.
- Every agent receives bounded files, bounded context, and a bounded retry/token budget.
- No run is complete without verification evidence.
- No repository write is finalized before user review.

## Version-1 completion gate

Version 1 is not complete until a non-developer user can install a supported platform package, import the approved project through the guided UI, submit the homepage task, review the generated plan, execute it through Empy, inspect verification and diffs, and accept or revert the result without entering a terminal command. The same acceptance flow must pass on macOS, Linux, and Windows using the shared Web Desktop path.
