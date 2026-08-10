# Ticket 14 — Verification Pipeline in UI

Ticket 14 connects project-aware verification to the Desktop product.

## Scope

- Map real verification commands from the detected project type or `.empy/verification.json`.
- Execute Tests, Build, and Lint commands outside Tk's UI thread.
- Stream stdout and stderr into the corresponding UI panel.
- Persist JSON reports plus stdout/stderr evidence per check.
- Keep Finalize disabled and rejected by the domain gate until every check passes.

## Project mapping

Python projects use pytest, compileall, and Ruff. Laravel, Node, Rust, Go, and plain PHP receive commands appropriate to their detected project structure. Plain PHP projects without Composer or PHPUnit use safe `php -l` checks for source files, including projects whose PHP files live below the root such as `public_html/`. Projects can override mapping with `.empy/verification.json` using explicit argument arrays; commands are never interpreted through a shell.

## Failure and continuation contract

Verification is a gate, not a terminal crash. If no safe check is mapped, Empy
persists a failed report with a diagnostic and keeps export blocked. If a check
fails, the result screen exposes the check label, exit code, and bounded,
redacted evidence. The `Continue and fix ticket` action keeps the same isolated
project, preserves the failed ticket in history, and carries the safe findings
into a new ticket objective so the next Agent run can address the actual cause.

Generic HTML entry files and PHP source files below the project root are
eligible for ownership by the matching writing Agent. This prevents planning
from failing before verification on ordinary projects such as a plain
`public_html/` application.

## Finalize gate

`VerificationReport.finalize_allowed` is true only when the report status is `pass`, at least one real check ran, and every result passed. The workspace adapter also enforces the gate, so bypassing the disabled UI button cannot finalize failed evidence.
