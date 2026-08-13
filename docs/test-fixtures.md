# Test fixtures

Empy Studio uses `examples/fixtures/php-site` as its repository-owned PHP
acceptance project. It is intentionally small, dependency-free, deterministic,
and safe to modify only in a temporary copied workspace during tests.

The fixture is not a default project in a user's workspace and is not mixed
with a user's imported projects. The real Holda project remains external and
read-only; it can still be supplied as an optional, one-off witness when a
real-project acceptance run is needed, but Empy's normal tests do not depend on
it and no Holda source belongs in this repository.
