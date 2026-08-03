# Context Builder

The Context Builder turns a Project Vault and one request into a small, task-specific package for a coding agent.

```bash
empy context build \
  --vault ./project_vaults/my-project \
  --request ./request.json \
  --output-dir ./context/security-review \
  --max-bytes 64000
```

The package contains:

- `request.json`
- project identity and locked decisions
- `CONTEXT.md`
- `context.json` with byte and token estimates
- only the selected source files under `files/`

Explicit files may be forced into the package:

```bash
empy context build ... --include src/auth.py --include config/routes.py
```

The builder never silently scans beyond the Project Vault baseline. It records files excluded because of low relevance or the context budget.
