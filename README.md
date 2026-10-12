# Empy Studio

Empy Studio accepts a project archive and a concrete change request, builds a
small auditable agent plan, verifies the resulting diff, and produces a ZIP
that preserves the original project paths.

This repository is the clean Laravel rebuild. Historical Empy releases and
unrelated acceptance fixtures are not dependencies of this product.

## Product workflow

1. Import a project ZIP into an isolated workspace. The original archive and
   unrelated test projects are never used as writable state.
2. Enter one concrete Ticket. Empy indexes the project once, assigns each
   writable path to one agent role, and stores a fingerprinted plan.
3. Run the configured model provider. The provider returns structured file
   content; Empy is the only writer and rejects out-of-scope paths.
4. Verify the real diff and syntax. A transient checker failure can be retried
   on the same Ticket without invoking the model again.
5. Deliver a ZIP only after Verification passes. The archive contains the
   project files and manifest, preserves paths, excludes secrets, and records a
   SHA-256 checksum.

The release process includes Laravel tests, lint and packaging checks, a clean
macOS runtime smoke test, and a live Ticket from import through extracted ZIP.

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
writer. When Codex is used, the prompt contains only the assigned paths and
their SHA-256 values; Codex reads those files from the mounted workspace. If a
file changes after planning, the run stops safely instead of sending stale
content to a fallback provider. Ollama and OpenAI-compatible endpoints are
explicit inline-context fallback options; paid services are never enabled
silently.

The desktop packaging script builds an application bundle with the Laravel
runtime and a first-run launcher. It does not copy credentials into the bundle;
the user's existing ChatGPT/Codex sign-in remains in the OS profile. The first
launch creates the local database and storage directories; a one-time Codex
sign-in is the only model setup when no session already exists.
