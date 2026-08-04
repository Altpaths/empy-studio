# Repository and Product Baseline

## Baseline conclusion

The repository contains a substantial Python control-plane and orchestration engine, but it does not yet contain the independent end-user desktop product defined for Empy Studio v1.

## Reusable implementation already present

- Project Vault and bounded context construction.
- Task planning, execution graphs, capability scheduling, and multi-agent runtime primitives.
- Agent contracts, adapters, registry, scheduler, and memory.
- Codex workflow, materialization, execution, session, doctor, and CLI modules.
- Verification, security audit, environment checks, quality evidence, and real-project scenario tooling.
- Release, distribution, installer, uninstaller, GitHub publication, and artifact-management modules.
- Plugin package and lifecycle infrastructure.

These assets are candidates for reuse behind the product boundary. Their presence does not by itself mean the corresponding desktop user journey exists.

## Missing product-facing capabilities

- Desktop application shell.
- Finder project picker and recent-project workspace.
- Natural-language task composer and task templates.
- Plan approval interface.
- Visible agent routing and token-budget controls.
- Desktop execution progress and cancellation.
- Integrated verification and diff review.
- Accept and revert workflow.
- Downloadable macOS application package.

## Important repository finding

The uploaded `main` archive does not include the Ticket 9 modules previously developed locally (`task_input.py`, `project_resolver.py`, `task_orchestrator.py`, `task_runtime.py`, and related files). Product work must therefore use only code actually present in this baseline unless those modules are deliberately recovered or reimplemented within an approved roadmap ticket.

## Quality status

The repository contains a CI workflow for Python 3.10, 3.11, and 3.12 using Ruff, MyPy, and Pytest. A fresh full quality-gate run could not be completed in the isolated audit environment because its offline package index did not expose the configured Hatchling build dependency. This baseline therefore records structure and scope accurately but does not falsely claim an independent green run.

## Locked next step

The only next permitted roadmap item is **Ticket 2 — Core / Desktop / Driver Boundaries**.
