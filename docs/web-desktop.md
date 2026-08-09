# Guided Desktop UI

`empy-web` is the bilingual local UI used by the macOS acceptance package.
It is intentionally a local HTTP application rather than a hosted service:

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
5. Accept or revert the changes and export a direct single-root project ZIP.

The header uses the EMPY brand asset. The plan screen exposes a provider-free
local benchmark for full versus bounded context, while completed runs expose
provider usage only when the driver receives structured usage events. Project
Brain reuse and context selection are persisted per imported project so a
follow-up ticket does not repeat the full discovery pass.

The SQLite workspace records project and ticket history. Resetting the current
screen clears the active selection but does not delete an imported project or
its evidence.

## Security boundary

- The original selected folder is not edited.
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
