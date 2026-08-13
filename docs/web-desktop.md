# Guided Desktop UI

`empy-web` is the bilingual local UI used by the supported Empy Studio
packages. It is intentionally a local HTTP application rather than a hosted
service and runs on macOS, Linux, and Windows:

```bash
empy-web
```

The command prints a loopback URL containing a random per-process token and
opens it in the default browser. API requests without the token are rejected.

## Product flow

1. Import a project folder or ZIP.
2. Empy copies the project into an isolated workspace, creates a local Git
   baseline, and initializes a Project Vault.
3. Add a natural-language ticket and review the generated agent graph, owned
   files, selected context, and token cap.
4. Run Codex through the bounded driver, then inspect verification and review
   evidence.
5. Accept or revert the changes, export a direct single-root project ZIP, and
   download it from the verified result screen.

The guided Web Desktop is the canonical product path used by every platform
package. Folder and ZIP selection use browser file inputs and upload into the
isolated local workspace; macOS native dialogs remain an optional fallback.
This avoids a macOS-only dependency on AppleScript. The UI also provides
bilingual status/error messages, Codex readiness refresh, accessibility labels,
and an authenticated local engine-opening action. The older Tk shell remains
available as a developer compatibility surface.

The header uses the EMPY brand asset. The plan screen exposes a provider-free
local benchmark for full versus bounded context, while completed runs expose
provider usage only when the driver receives structured usage events. Project
Brain reuse and context selection are persisted per imported project so a
follow-up ticket does not repeat the full discovery pass.

Import and delivery use different safety policies. Existing runtime
dependencies such as vendor/ and node_modules/ are preserved in Empy's
isolated execution copy so the project's own checks can run; they remain
excluded from Agent context and from the final delivery ZIP. A static
Verification preflight is shown immediately after import, so missing
dependencies or an invalid verification contract are visible before an Agent
run consumes tokens. When a check expects a different entry point than the
project provides, Empy reports the contract mismatch and does not recommend a
placeholder file.

The SQLite workspace records project and ticket history. Resetting the current
screen clears the active selection but does not delete an imported project or
its evidence.

The result screen exposes an authenticated local `Download ZIP` action. Empy
streams only the current verified archive, confirms that it remains inside the
workspace, and rechecks its recorded SHA-256 before sending it to the browser.
If the archive is missing or has changed, the download is rejected and a new
export is required.

After a run, the result screen shows a compact report for every graph node:
agent identity, role, status, duration, changed files, provider-reported usage
when available, local estimate source, and safe workspace-relative evidence
references. It also exposes the dependency-wave schedule and whether each wave
ran serially or in a bounded parallel batch. Missing provider usage is shown as
`not_reported`; it is never converted into an exact value.

## Security boundary

- The original selected folder is not edited.
- Browser uploads are bounded per file and in total, reject traversal and
  sensitive members, and are deleted after import.
- System roots, user roots, and macOS AppTranslocation paths are rejected as
  project sources; users must choose the actual project folder or ZIP.
- ZIP extraction rejects traversal and symlink members and applies size limits.
- `.env`, private keys, dependency directories, Git history, and temporary
  files are not copied to a delivery archive.
- The UI does not install a remote script automatically. Provider installation
  and authentication remain explicit user actions.
- The UI never commits, pushes, merges, tags, or publishes a project.
- Browser actions use one event-delegation boundary rather than inline global
  handlers, keeping the local UI compatible with a stricter content-security
  policy.

Hosts that already provide an external sandbox may explicitly inject a
`CodexDriver(sandbox_mode="danger-full-access")` for a controlled integration
test. Empy does not select that mode by default; the normal driver derives
`read-only` or `workspace-write` from the approved node scope.
