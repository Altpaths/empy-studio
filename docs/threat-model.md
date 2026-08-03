# Threat Model

Empy Studio assumes coding agents may make incorrect, over-broad, or unsafe changes.

Primary risks:

- Secret exposure
- Prompt injection through repository content
- Unbounded file access
- Concurrent edits to shared files
- Destructive commands
- False claims about test execution
- Contamination of global knowledge with project-specific preferences

Current mitigations:

- Explicit scopes and stop conditions
- One write owner per file per wave
- Structured local verification
- Pending state for external checks
- Evidence and scope requirements for learning

Empy Studio does not yet provide a hardened sandbox. Run untrusted agent commands in an isolated container or VM.
