"""Shared path-safety rules for project analysis, execution, and delivery.

The execution graph, provider runtime, synchroniser, and delivery code all
operate on project-relative paths.  Keeping the lexical, generated-file, and
real-path checks here prevents one layer from accepting a path that another
layer would silently drop or resolve outside the project.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Final

# These names are deliberately a superset of the import and delivery
# exclusions.  A provider must not be allowed to edit an artefact that the
# final ZIP drops, nor may a broad creation scope reach generated dependency
# trees.  Keeping the set here also lets the runtime fail closed before a
# provider spends a turn on a doomed edit.
PROJECT_EXCLUDED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".empy",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "env",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".parcel-cache",
        "__pycache__",
        "__macosx",
        "artifacts",
        ".gradle",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "outputs",
        "out",
        "private",
        "project_vaults",
        "releases",
        "target",
        "vendor",
        "venv",
        "work",
    }
)

PROJECT_EXCLUDED_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".ds_store",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "pipfile.lock",
        "cargo.lock",
        "go.sum",
    }
)

PROJECT_GENERATED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".map",
    ".min.js",
    ".min.css",
    ".lock",
)

PROJECT_EXCLUDED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".zip",
)

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


def normalize_relative_path(
    relative_path: str | PurePosixPath,
    *,
    allow_directory: bool = False,
) -> str:
    """Return a canonical project-relative path or raise for unsafe input.

    ``PurePosixPath`` is used intentionally: project paths in manifests and
    provider reports are POSIX-shaped even when Empy runs on Windows.  A
    trailing slash is retained only for an explicitly allowed directory
    creation scope.  The project root itself is never a valid target.
    """

    raw = str(relative_path).replace("\\", "/").strip()
    if not raw or "\x00" in raw:
        raise ValueError(f"unsafe relative path: {relative_path}")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError(f"unsafe relative path: {relative_path}")
    had_trailing_slash = raw.endswith("/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {relative_path}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"unsafe relative path: {relative_path}")
    if had_trailing_slash:
        if not allow_directory:
            raise ValueError(f"directory scope is not allowed here: {relative_path}")
        return normalized.rstrip("/") + "/"
    return normalized


def is_root_scope(relative_path: str | PurePosixPath) -> bool:
    """Return whether a scope denotes the entire project root."""

    raw = str(relative_path).replace("\\", "/").strip()
    return raw in {"", ".", "./", "/"}


def is_directory_scope(relative_path: str | PurePosixPath) -> bool:
    """Return whether a path is an approved directory creation scope."""

    return str(relative_path).replace("\\", "/").rstrip().endswith("/")


def _parts_for_policy(relative_path: str | PurePosixPath) -> tuple[str, ...]:
    normalized = normalize_relative_path(relative_path, allow_directory=True)
    return tuple(
        part.casefold()
        for part in normalized.rstrip("/").split("/")
        if part and part != "."
    )


def is_generated_relative_path(relative_path: str | PurePosixPath) -> bool:
    """Return whether a path is generated, dependency, or lockfile output."""

    try:
        parts = _parts_for_policy(relative_path)
    except ValueError:
        # A caller that asks about an unsafe path must fail closed.  The
        # lexical validator still reports the traversal detail to callers
        # that need it; policy predicates should never accidentally permit it.
        return True
    if not parts:
        return False
    name = parts[-1]
    return (
        name in PROJECT_EXCLUDED_FILE_NAMES
        or any(part in PROJECT_EXCLUDED_DIRECTORY_NAMES for part in parts)
        or any(name.endswith(suffix) for suffix in PROJECT_GENERATED_SUFFIXES)
    )


def is_delivery_excluded_relative_path(
    relative_path: str | PurePosixPath,
) -> bool:
    """Return whether the final delivery walker intentionally drops a path."""

    try:
        parts = _parts_for_policy(relative_path)
    except ValueError:
        return True
    if not parts:
        return False
    name = parts[-1]
    return (
        any(part in PROJECT_EXCLUDED_DIRECTORY_NAMES for part in parts)
        or name in PROJECT_EXCLUDED_FILE_NAMES
        or name.startswith(".env.")
        or any(name.endswith(suffix) for suffix in PROJECT_EXCLUDED_SUFFIXES)
        or is_sensitive_relative_path(relative_path)
    )


def is_agent_denied_relative_path(
    relative_path: str | PurePosixPath,
) -> bool:
    """Return whether provider execution and synchronisation must deny it."""

    return is_delivery_excluded_relative_path(relative_path) or is_generated_relative_path(
        relative_path
    )


def project_path(
    project_root: str | Path,
    relative_path: str | PurePosixPath,
    *,
    allow_directory: bool = True,
) -> Path:
    """Resolve a project-relative path without following a symlink component.

    A path is denied when its lexical components contain a symlink, even if
    that symlink happens to point back inside the project.  This makes the
    ownership contract stable between the preflight snapshot and the write.
    Missing final components are supported for exact creation targets.
    """

    normalized = normalize_relative_path(relative_path, allow_directory=allow_directory)
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project root is not a directory: {project_root}")
    parts = PurePosixPath(normalized.rstrip("/")).parts
    candidate = root.joinpath(*parts)
    probe = root
    try:
        for part in parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError(f"symlink path component is not allowed: {normalized}")
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"could not resolve project path: {normalized}") from exc
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes project root: {normalized}")
    if not allow_directory and candidate.exists() and candidate.is_dir():
        raise ValueError(f"path is a directory, not a file: {normalized}")
    if is_directory_scope(normalized) and candidate.exists() and not candidate.is_dir():
        raise ValueError(f"directory scope points to a file: {normalized}")
    return candidate


def scope_contains(
    scope: str | PurePosixPath,
    relative_path: str | PurePosixPath,
) -> bool:
    """Return whether an exact path is covered by a file or dir scope."""

    if is_root_scope(scope):
        return False
    try:
        normalized_scope = normalize_relative_path(scope, allow_directory=True)
        normalized_path = normalize_relative_path(relative_path)
    except ValueError:
        return False
    if is_directory_scope(normalized_scope):
        prefix = normalized_scope.rstrip("/")
        return normalized_path.startswith(prefix + "/")
    return normalized_path == normalized_scope


def scopes_overlap(
    first: str | PurePosixPath,
    second: str | PurePosixPath,
) -> bool:
    """Return whether two ownership scopes can address the same file."""

    if is_root_scope(first) or is_root_scope(second):
        return True
    try:
        left = normalize_relative_path(first, allow_directory=True)
        right = normalize_relative_path(second, allow_directory=True)
    except ValueError:
        return True
    if left == right:
        return True
    if is_directory_scope(left) and scope_contains(left, right.rstrip("/")):
        return True
    return is_directory_scope(right) and scope_contains(right, left.rstrip("/"))


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
