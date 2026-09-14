# Packaged macOS acceptance

Build the normal persistent app with `scripts/build_macos_app.py`. Its two bundle version fields must match the source `project.version` before signing. `--clean-workspace` is an explicit disposable test option and is not used for release builds.

Run the acceptance harness against the built or downloaded app:

```sh
python scripts/run_macos_app_acceptance.py --app '/path/Empy Studio.app' --release-tag vX.Y.Z --evidence-dir /tmp/empy-normal --repetitions 2
python scripts/run_macos_app_acceptance.py --app '/path/Empy Studio.app' --release-tag vX.Y.Z --evidence-dir /tmp/empy-recovery --scenario recovery --repetitions 2
```

Install Playwright and its Chromium browser first. If browser download is unavailable, pass `--browser-executable '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`. The harness starts a new isolated automated browser and never attaches to a user's browser profile.

Each repetition imports a ZIP, completes two separate tickets through the UI, requires finalized successful Node verification, accepts changes, verifies ZIP and sidecars, and compares the exact accepted project/task/run/verification/review/export after app restart. It also checks both ticket IDs remain in history. Deployment into a fresh original fixture must preserve unchanged file hashes and timestamps and must not create duplicate `public_html/public_html` nesting.

The recovery scenario makes the deterministic Codex CLI double produce two distinct real verification failures on each ticket; its third execution fixes the output. No manual retry is clicked. The harness requires exactly three executions per ticket and a verified recovery state. This tests application orchestration with a fake provider, not live Codex behavior, real token billing, Apple notarization, or Gatekeeper approval.

Evidence includes screenshots, API state snapshots, browser video when using the bundled Playwright browser, Playwright trace, app/console logs, ZIP/manifest/checksum downloads, a JSON check summary, and a Markdown report. Failure snapshots and traces are captured while the browser is still alive. Use a fresh evidence directory for each invocation. Never treat a result-screen heading alone as successful verification.
