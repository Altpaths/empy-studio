# Empy Studio

Empy Studio accepts a project archive and a concrete change request, builds a
small auditable agent plan, verifies the resulting diff, and produces a ZIP
that preserves the original project paths.

This repository is the clean Laravel rebuild. Historical Empy releases and
unrelated acceptance fixtures are not dependencies of this product.

## Current state

The implementation is being delivered in gated stages. See `.empy/` for the
approved product contract and execution plan. A release is valid only when the
tests and extraction smoke test pass.

## Development

```bash
composer install
cp .env.example .env
php artisan key:generate
touch database/database.sqlite
php artisan migrate
php artisan serve
```

The same steps can be run with `composer run setup` when Node/npm is available.

The default local mode can build a project index without a model provider. For
the lowest-friction macOS setup, install/sign in to the Codex CLI with your
ChatGPT account and leave `EMPY_PROVIDER_ORDER=codex,ollama,openai_compatible`.
Empy invokes Codex in an ephemeral, read-only workspace and remains the only
writer. Ollama and OpenAI-compatible endpoints are explicit fallback options;
paid services are never enabled silently.

The desktop packaging script builds an application bundle with the Laravel
runtime and a first-run launcher. It does not copy credentials into the bundle;
the user's existing ChatGPT/Codex sign-in remains in the OS profile.
