# Customer request

We need a repeatable release process for a Python command-line project.

The process must:

- run Ruff, MyPy, tests, and coverage;
- block publishing when CI fails;
- generate platform-specific installers;
- preserve GitHub Release asset download counters;
- support clean uninstall;
- retain evidence for every release decision.

The next action is to validate the complete Release Candidate on a clean
environment before publishing version 1.0.0.
