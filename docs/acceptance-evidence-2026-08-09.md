# Acceptance Evidence — 2026-08-09

This record belongs to the `codex/product-continuity-roadmap` implementation
branch and is intentionally separate from the immutable ZIP audit baseline.
It records checks that actually ran; it does not declare the complete T00–T18
roadmap finished.

## Repository checks

- Repository: `Altpaths/empy-studio`
- Branch: `codex/product-continuity-roadmap`
- PR: [#31](https://github.com/Altpaths/empy-studio/pull/31)
- Python: 3.12.13 on Apple Silicon
- Full suite after the current wave: `493 passed`
- Ruff: `All checks passed!`
- `python -m compileall -q src`: passed
- `empy-web --help`: passed
- Wheel build and static web-asset inspection: passed

## Real provider acceptance

The test used the installed and authenticated local Codex CLI (`codex-cli
0.146.0`) against a freshly imported copy of a small Python project. The
approved ticket required a new `shout(name: str) -> str` helper in
`src/service.py`, while preserving `greet` and limiting the change to the
backend source file.

Observed result:

- `node-discovery`: completed
- `node-implement-backend`: completed
- `node-quality`: completed
- Codex changed the requested source file and left `greet` unchanged.
- Review contained exactly `src/service.py`; generated `__pycache__`, pytest,
  Ruff cache, and sensitive paths were excluded.
- Project verification passed: Python tests (`1 passed`), compileall, and Ruff.
- The accepted project exported as a single-root ZIP with `file_count: 3`.
- Export verification: `verified: true`
- Acceptance ZIP SHA-256:
  `a994a8f4789258e2892aed6f9f2ebec5ec4d1f06ac7c59c94789b21692965c7a`

The temporary acceptance workspace was:
`/var/folders/f4/4dnx2gx111j1xbwz0lvkz63m0000gn/T/empy-e2e-fixed-jpvs9bh1`.
The archive, manifest, checksum, run evidence, and verification evidence were
created there by the product workflow.

## Environment limitation

An initial real run using Empy's normal derived sandbox mode was stopped by
the host's nested Codex sandbox with `Operation not permitted` while opening
the Codex state database. The acceptance run therefore injected
`CodexDriver(sandbox_mode="danger-full-access")` explicitly for the isolated
temporary workspace. This is a host-integration test workaround, not Empy's
default: normal execution still derives `read-only` or `workspace-write` from
approved ownership.

## Remaining scope

The continuity path is now exercised end-to-end, but the full product roadmap
still requires clean-machine UI acceptance, richer reopen/resume behavior,
additional providers, packaging/signing, and the remaining T01–T18 acceptance
criteria. The PR remains draft until those gates are reviewed.
