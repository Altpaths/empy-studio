# Getting started

## Install for development

```bash
git clone <repository-url>
cd empy-studio
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
pytest
```

## Plan a request

```bash
empy plan   --project examples/project.json   --request examples/request.json
```

The output contains domains, tasks, dependencies, execution waves, file scopes, and ownership conflicts.

## Verify a release

```bash
empy verify   --manifest examples/runtime-manifest.json
```

Local checks execute. Checks requiring a live host, production database, payment gateway, email service, or browser remain explicitly pending.

## Learn from a completed sprint

```bash
empy learn   --graph examples/graph.json   --sprint examples/sprint.json
```

Only validated and reusable lessons are merged.
