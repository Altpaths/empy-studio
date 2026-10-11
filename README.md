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
php artisan migrate
php artisan serve
```

The default local mode can build a project index without a model provider. To
execute model-backed changes, configure a local Ollama model or an
OpenAI-compatible endpoint in `.env`. Paid services are never enabled silently.
