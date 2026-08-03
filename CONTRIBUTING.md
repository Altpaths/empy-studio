# Contributing to Empy Studio

Empy Studio welcomes focused contributions that keep the project lightweight.

## Before proposing a feature

Explain which measurable problem it addresses:

- token consumption;
- repeated work;
- context reconstruction;
- file conflicts;
- verification quality;
- release friction;
- cross-project learning.

A feature that only adds flexibility or abstraction is unlikely to enter the core.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## Pull requests

Keep each pull request bounded. Include:

- problem and intended outcome;
- files changed;
- tests actually run;
- compatibility impact;
- documentation changes;
- remaining risks.

Do not include private Project Vaults, credentials, production data, generated caches, or personal project source code.
