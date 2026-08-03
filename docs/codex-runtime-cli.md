# Codex Runtime Integration and CLI

Ticket 5.6 connects environment diagnosis, initial execution, session resume,
evidence, manual fallback, and the Empy Studio CLI.

Commands:

```bash
empy codex doctor --manifest RUN/manifest.json
empy codex run --manifest RUN/manifest.json
empy codex resume --manifest RUN/manifest.json --prompt "Continue"
empy codex manual --manifest RUN/manifest.json --reason "..."
empy codex status --manifest RUN/manifest.json
```
