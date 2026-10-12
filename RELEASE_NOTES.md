# Empy Studio Laravel 1.1.8

## Delivered behavior

- Imports a ZIP into a project-specific workspace with traversal and symlink
  checks.
- Builds a compact manifest with hashes, framework hints, and entry points.
- Creates a one-writer-per-file plan before any provider call.
- Sends only planned file context and records provider attempts and usage.
- Uses an explicit workspace-read capability for Codex: only assigned paths and
  hashes enter the prompt, while adapters without that capability retain the
  inline fallback.
- Stops on a stale workspace hash rather than routing old file bytes to another
  provider.
- Supports a signed-in local Codex CLI, local Ollama, and OpenAI-compatible
  endpoints with ordered fallback. Codex runs ephemeral and read-only; Empy
  remains the only writer.
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

The application does not contain model weights. On macOS, configure
`EMPY_PROVIDER_ORDER=codex,ollama,openai_compatible` and sign in to the Codex
CLI with ChatGPT to use the existing plan without an API key. Ollama and an
OpenAI-compatible endpoint remain explicit alternatives. If none is
configured, planning remains available and execution stops with a clear
`provider_unavailable` message; paid services are never enabled silently.

## Release limits

The provider's own quota, model quality, network, and project-specific build
tools remain external conditions. Empy avoids wasting context and repeated
calls, but it cannot manufacture a missing provider or guarantee an arbitrary
future codebase without executing its actual tests.
