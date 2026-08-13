# Empy PHP fixture

This is a small, dependency-free PHP project used by Empy Studio's real-flow
acceptance tests. It is safe, deterministic, and independent of any user's
production project.

The fixture is copied into a temporary Empy workspace before a test run. The
fixture files in this repository are never edited by the test.

Run its check with:

```sh
php tests/site-audit.php
```
