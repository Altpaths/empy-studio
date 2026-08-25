# Execution Status

This file records evidence for the approved product roadmap. It is updated at
the end of each implementation wave.

## 2026-08-09 — baseline

- Repository: `Altpaths/empy-studio`
- Starting commit: `39239f5a88b1f35bef095d8ed35f2832031016fc`
- Working branch: `codex/product-continuity-roadmap`
- Python used: 3.12.13 (Apple Silicon)
- Baseline tests: 481 passed, 1 failed
- Baseline Ruff: passed
- Baseline compileall: passed
- Baseline CLI help: passed
- Baseline failure: `test_missing_installation_has_clear_remediation` detected a
  locally installed Codex fallback despite the test hiding PATH lookup.

The immutable input hashes and working-copy map are recorded in
[`baseline-audit-2026-08-09.json`](baseline-audit-2026-08-09.json).

The baseline failure is being fixed as a determinism/testability issue before
new product behavior is merged.

## 2026-08-09 — continuity wave

- Current branch: `codex/product-continuity-roadmap`
- Current suite: 495 passed
- Real Codex graph acceptance: discovery, backend implementation, and quality
  nodes completed on an imported project.
- Real verification: tests, compile, and Ruff passed.
- Real review: only the approved source file remained visible after generated
  and sensitive paths were filtered.
- Real delivery: project-relative change-only ZIP, manifest, checksum, and
  DirectAdmin-root extraction verification passed.
- Workspace restart now restores the active project, active ticket, contract,
  plan, graph, and selectable ticket history.
- Workspace schema v2 records and restores verified project release history.
- Interactive loopback UI smoke test passed for bilingual toggle, plan,
  ticket history/resume, Codex readiness, and unauthorized API rejection.
- Detailed evidence: [`acceptance-evidence-2026-08-09.md`](acceptance-evidence-2026-08-09.md)
- The PR is intentionally still draft; main has not been merged without the
  final integration decision.

## 2026-08-09 — approved integration and product hardening

- The approved continuity wave is integrated locally on `main` at commit
  `9098110`, with the six commits after the integrated baseline preserved in
  history.
- The duplicate legacy `release build` dispatch was removed. The CLI now has
  one manifest-driven release route, and a regression test covers its actual
  dispatch rather than only parser construction.
- A canonical `release-manifest.json` and a complete release-build example are
  now present in the repository, so the documented release path is executable.
- Project Brain reuse avoids a second full repository walk when the index is
  valid; the UI reports measured provider usage separately from the local
  token-efficiency estimate.
- The bilingual Desktop UI uses delegated actions, CSP-safe event handling, and
  the EMPY logo at `src/empy_studio/web/empy-logo.png`.
- Final verification for this wave passed: 515 tests, Ruff, MyPy, compileall,
  CLI help, release validation, and browser asset smoke. The resulting changes
  are present on local `main`.
