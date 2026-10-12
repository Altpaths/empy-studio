# Acceptance Report — Workspace Isolation and Provider Context

## Baseline

- Branch: `desktop-product`
- Baseline commit: `7e3f15c`
- Scope: ticket baselines, explicit managed-workspace reset, and bounded workspace-read context

## Implemented

- Each planned ticket stores the project manifest that existed when its plan was validated.
- Verification compares against that ticket baseline and advances the project manifest only after a successful verification.
- Legacy tickets without a stored baseline fall back to the project manifest.
- `empy:reset-workspace` requires `--force`, supports `--dry-run` and `--keep-settings`, removes only allowlisted Empy-managed state, and recreates required directories.
- Broad, empty, relative, root, home, bundled-source, and symlink reset roots are rejected.
- Providers can opt into a separate workspace-read capability without changing the inline fallback used by API/local adapters.
- Codex receives only the assigned workspace paths and SHA-256 values in workspace-read mode; the file body is not placed in its prompt.
- A hash mismatch stops the run instead of falling back to an inline provider with stale bytes.
- Codex remains `--ephemeral`; no conversational state is shared across unrelated tickets.
- Run and provider events record whether context was inline or workspace-read and include estimated token savings.

## Validation

- `php artisan test --no-coverage`: 36 passed, 197 assertions.
- `vendor/bin/pint --test`: passed.
- PHP syntax checks: passed.
- `git diff --check`: passed.
- Sequential-ticket regression: passed.
- Reset refusal, deletion/recreation, settings preservation, and empty-root safety: passed.
- Workspace-read prompt, provider fallback, stale-context stop, and execution accounting: passed.

## Delivery notes

- The reset command does not stop a running server. The desktop app must be closed before a destructive reset.
- Provider API/local adapters that do not support workspace-read still receive the relevant file content inline. Their cross-ticket token use is not reduced by a hidden session or fabricated cache.
- Codex workspace-read is guarded by an allowlist and preflight hash check, but the Codex CLI itself does not expose a hard per-file read sandbox; the prompt contract and hash validation are the enforceable boundary.
- No real user workspace was deleted during validation.
