# Empy Studio Laravel 1.0.0

## Delivered behavior

- Imports a ZIP into a project-specific workspace with traversal and symlink
  checks.
- Builds a compact manifest with hashes, framework hints, and entry points.
- Creates a one-writer-per-file plan before any provider call.
- Sends only planned file context and records provider attempts and usage.
- Supports local Ollama and OpenAI-compatible endpoints with ordered fallback.
- Applies structured full-file patches atomically and rolls them back on error.
- Uses changed-graph recovery and refuses blind replay of the same failure.
- Verifies a real project diff and PHP/JSON syntax where applicable.
- Produces a path-preserving ZIP, excludes `.env` secrets, and records SHA-256.
- Presents plain-language errors in the UI instead of raw agent logs.

## Verification evidence

- Laravel Pint: passed.
- Feature/unit tests: 18 passed, 88 assertions.
- HTTP smoke test from an extracted checkout: HTTP 200.
- Clean extraction and composer install: passed.

## Configuration boundary

The application does not contain a model. Configure Ollama or an
OpenAI-compatible endpoint in `.env` for model-backed execution. If neither is
configured, planning remains available and execution stops with a clear
`provider_unavailable` message; paid services are never enabled silently.

## Release limits

The provider's own quota, model quality, network, and project-specific build
tools remain external conditions. Empy avoids wasting context and repeated
calls, but it cannot manufacture a missing provider or guarantee an arbitrary
future codebase without executing its actual tests.
