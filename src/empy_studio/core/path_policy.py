"""Shared path-safety rules for project analysis, context, and delivery."""

from __future__ import annotations

from pathlib import PurePosixPath

SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials",
        "credentials.json",
        "secrets.json",
        "secret.json",
        "config.php",
        "config.local.php",
        "settings.php",
        "settings.local.php",
        "parameters.php",
        "parameters.local.php",
        "secrets.php",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
        "known_hosts",
    }
)

SENSITIVE_DIRECTORY_NAMES = frozenset(
    {
        "secrets",
        "credentials",
        ".ssh",
        ".gnupg",
        "log",
        "logs",
    }
)

SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".log",
)


def is_sensitive_relative_path(relative_path: str | PurePosixPath) -> bool:
    """Return whether a relative project path must not enter AI context or ZIPs."""

    parts = tuple(
        part.lower()
        for part in str(relative_path).replace("\\", "/").split("/")
        if part and part != "."
    )
    if not parts:
        return False

    name = parts[-1]
    if name in SENSITIVE_FILE_NAMES:
        return True
    if name.startswith(".env"):
        return True
    if any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return True
    return any(part in SENSITIVE_DIRECTORY_NAMES for part in parts)
