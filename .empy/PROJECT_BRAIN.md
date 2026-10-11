# Empy Laravel Product Brain

## Identity

- Product: Empy Studio Laravel rebuild
- Purpose: accept one project archive, plan a bounded agent workflow, apply only
  verified project changes, and produce an extractable ZIP.
- Baseline: earlier Python/macOS Empy releases are evidence only. They are not
  source code for this product and no Alpha, Holder, or prior fixture is copied
  into this tree.

## Runtime

- PHP 8.5.5 is available in the development environment.
- Laravel 13.35.0 is locked in `composer.lock`.
- SQLite is the default local database.
- Blade and small, dependency-free browser scripts are preferred for the first
  release. A queue-backed job path is used where it improves reliability.

## Product boundary

1. Import a ZIP into a dedicated workspace without path traversal or cross-run
   contamination.
2. Build a compact manifest with hashes and likely entry points.
3. Turn a ticket into a validated task graph with one writer per file.
4. Execute through configured provider adapters without rereading unchanged
   files or replaying the same failed graph.
5. Verify that the requested change happened and that no unowned file changed.
6. Export the project with relative paths preserved and emit a checksum.

## Non-goals

- No Alpha, Holder, or historical test project belongs in this repository.
- No hidden paid provider is enabled.
- No artificial token ceiling is used as a substitute for context reduction.
- No success is reported when no project file changed or verification fails.

## Evidence status

- FACT: Laravel skeleton was created with Composer and default migrations passed.
- UNKNOWN: which provider the end user will configure; the app must surface
  this as setup state rather than silently failing.
- BLOCKED until implemented: import, planning, execution, verification, and
  delivery.
