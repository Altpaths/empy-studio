# Security policy

## Supported versions

Security fixes are currently provided for the latest published Developer Preview.

## Reporting

Do not open a public issue for a suspected vulnerability.

Send a private report through the contact channel listed at [empy.ir](https://empy.ir). Include:

- affected version;
- reproduction steps;
- expected impact;
- proof of concept when safe;
- suggested mitigation, if known.

## Security boundaries

Empy Studio may execute user-defined verification commands. Treat manifests and project repositories as trusted inputs unless an isolated runner is used.

Never commit:

- credentials or `.env` files;
- private Project Vaults;
- production databases or logs;
- customer source code;
- release artifacts containing secrets.
