# Codex Environment Doctor

The Environment Doctor validates local readiness before Empy Studio invokes
Codex.

## Checks

The doctor reports:

- whether the Codex executable is present in `PATH`;
- the installed Codex version;
- whether `codex exec` is available;
- whether `codex login status` reports valid authentication;
- whether Codex reports known host PATH-alias, app-server, state, or sandbox
  initialization failures;
- whether the project root exists;
- whether `AGENTS.md`, the prompt, and Evidence Directory exist;
- whether the project is a Git repository;
- whether the Git working tree contains uncommitted changes.

## Status model

A missing Codex executable, failed authentication, unavailable `codex exec`, or
known host preflight failure makes the result `not_ready`.

A non-Git project or dirty working tree is reported as a warning rather than a
hard failure.

## Security

The doctor never reads credential files, API keys, access tokens, or
`~/.codex/auth.json`. Authentication is checked only through the official
`codex login status` command.

Codex execution is not performed in this stage.

The host preflight check only inspects output from the existing version,
`exec --help`, and login-status commands. It does not start a model turn and
does not consume provider tokens. It reports stable diagnostic codes without
persisting raw command output in the Doctor result.
