# Ticket 17 — Independent sample-project acceptance evidence

Date: 2026-08-13

## Scope

Ticket 17 validates the complete product path through Empy Studio itself. The
repository-owned PHP fixture at `examples/fixtures/php-site` is the normal
acceptance input and the user-facing sample. No external production project
is required by the test suite or bundled into the product.

## Acceptance scenario

The fixture is copied into a temporary Empy workspace before execution. The
fixture in Git is never edited. The deterministic scenario covers:

1. Import a PHP project through Empy into an isolated copy.
2. Build a bounded plan and run the local token benchmark.
3. Execute a ticket, inspect the change, accept it, and export a verified
   change-only ZIP.
4. Reopen the workspace and confirm run, verification, review, and export
   evidence are available.
5. Add a second ticket, execute it, accept the change, and export a second
   verified ZIP.
6. Import a second project and confirm its project/task history is separate.
7. Compare the fixture digest before and after the full flow.

The live local UI smoke also covers starting a real graph, cancelling it, and
confirming that the terminal state is shown without leaving the page in
`running`.

## Fixture use

Users can download the repository source archive, open
`examples/fixtures/php-site` in Empy Studio, and submit a normal ticket. The
fixture check is also available directly:

```sh
php examples/fixtures/php-site/tests/site-audit.php
```

The fixture is copied before execution and is never modified in place. A
user's imported project remains a separate workspace record.

## Boundary

No external user project is part of the repository, test suite, or release
runtime. No `.empy/` orchestration state is included in the product commit.
