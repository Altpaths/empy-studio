# Test fixtures

Empy Studio uses `examples/fixtures/php-site` as its repository-owned PHP
acceptance project. It is intentionally small, dependency-free, deterministic,
and safe to modify only in a temporary copied workspace during tests. It is the
independent sample project shipped for users who want to try the complete flow
without using a production project.

The fixture is not inserted automatically into a user's workspace and is not
mixed with imported projects. Empy copies it into an isolated working
directory before a test or demonstration run; the repository copy is never
edited.

To try it manually, download the repository source archive from GitHub, open
Empy Studio, choose the folder `examples/fixtures/php-site`, and submit a
ticket. An installed copy can be materialized without downloading a second
project:

```sh
empy sample --destination ~/empy-sample-project
```

Its deterministic check can also be run from that folder with:

```sh
php tests/site-audit.php
```
