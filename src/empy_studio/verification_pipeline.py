from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Literal, TextIO
from urllib.parse import unquote, urlsplit

from empy_studio.core.project_service import ProjectDetection
from empy_studio.dependency_bootstrap import (
    composer_dependencies_required,
    node_dependencies_required,
)

VerificationCategory = Literal["tests", "build", "lint"]
VerificationStream = Literal["stdout", "stderr", "system"]
VerificationStatus = Literal["pending", "running", "pass", "fail"]
VerificationResultStatus = Literal["pass", "fail"]

DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 1800.0
DEFAULT_PROCESS_GRACE_SECONDS = 2.0
MAX_VERIFICATION_MANIFEST_BYTES = 256 * 1024
MAX_VERIFICATION_CHECKS = 64
MAX_VERIFICATION_COMMAND_PARTS = 32
MAX_VERIFICATION_COMMAND_PART_BYTES = 4096
MAX_STATIC_WEB_FILE_BYTES = 4 * 1024 * 1024
MAX_STATIC_REPAIR_FILES = 32
MAX_STATIC_REPAIR_REPLACEMENTS = 128
_VERIFICATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_AUTO_LINT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".empy",
        ".venv",
        "node_modules",
        "vendor",
        "build",
        "dist",
        "storage",
        "cache",
        "__pycache__",
    }
)
_COMMON_TOOL_PATHS = tuple(
    Path(item).expanduser()
    for item in (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
        "~/.local/bin",
        "~/.npm-global/bin",
    )
)

_WEB_ROOT_NAMES = frozenset({"public_html", "public", "www", "htdocs"})
_HTML_SUFFIXES = frozenset({".html", ".htm"})
_CSS_SUFFIXES = frozenset({".css"})
_JS_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"})
_WEB_IGNORED_DIRECTORIES = _AUTO_LINT_IGNORED_DIRECTORIES | frozenset(
    {".next", ".nuxt", ".parcel-cache", ".svelte-kit", ".turbo", ".tox", ".nox"}
)


class VerificationCancelled(RuntimeError):
    """Raised after a verification subprocess has been stopped by the user."""


class VerificationTimedOut(RuntimeError):
    """Raised after a verification subprocess exceeds its bounded timeout."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    label: str
    category: VerificationCategory
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "label": self.label,
            "category": self.category,
            "command": list(self.command),
        }


@dataclass(frozen=True)
class VerificationEvent:
    timestamp: str
    check_id: str
    category: VerificationCategory
    stream: VerificationStream
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "check_id": self.check_id,
            "category": self.category,
            "stream": self.stream,
            "text": self.text,
        }


@dataclass(frozen=True)
class VerificationResult:
    check: VerificationCheck
    status: VerificationResultStatus
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.check.to_dict(),
            "status": self.status,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class VerificationReport:
    schema_version: int
    verification_id: str
    project_root: str
    project_type: str
    status: VerificationStatus
    started_at: str
    finished_at: str | None
    results: tuple[VerificationResult, ...]
    evidence_path: str
    finalized_at: str | None = None
    diagnostics: tuple[str, ...] = ()
    verification_root: str | None = None
    contract_signature: str | None = None

    @property
    def finalize_allowed(self) -> bool:
        return (
            self.status == "pass"
            and bool(self.results)
            and not self.diagnostics
            and all(item.status == "pass" for item in self.results)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "verification_id": self.verification_id,
            "project_root": self.project_root,
            "project_type": self.project_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": [item.to_dict() for item in self.results],
            "evidence_path": self.evidence_path,
            "finalize_allowed": self.finalize_allowed,
            "finalized_at": self.finalized_at,
            "diagnostics": list(self.diagnostics),
            "verification_root": self.verification_root,
            "contract_signature": self.contract_signature,
        }


@dataclass(frozen=True)
class VerificationPreflight:
    """Static readiness result shown before an Agent run starts."""

    checks: tuple[VerificationCheck, ...]
    diagnostics: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and not self.diagnostics

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "needs_attention",
            "checks": [item.label for item in self.checks],
            "diagnostics": list(self.diagnostics),
        }


def _node_scripts(root: Path) -> dict[str, object]:
    package = root / "package.json"
    if not package.is_file():
        return {}
    value = json.loads(package.read_text(encoding="utf-8"))
    scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
    return scripts if isinstance(scripts, dict) else {}


def _composer_scripts(root: Path) -> dict[str, object]:
    package = root / "composer.json"
    if not package.is_file():
        return {}
    value = json.loads(package.read_text(encoding="utf-8"))
    scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
    return scripts if isinstance(scripts, dict) else {}


def _php_source_files(root: Path) -> tuple[Path, ...]:
    """Return PHP source files that can be syntax-checked without executing them.

    A plain PHP project often has no Composer metadata or PHPUnit binary.  It
    still has a meaningful, safe verification gate: ``php -l`` parses each
    source file without running application code.  Dependency, generated, and
    Empy-owned directories are deliberately excluded.
    """

    source_files: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            directory
            for directory in directories
            if directory not in _AUTO_LINT_IGNORED_DIRECTORIES
            and not (current_path / directory).is_symlink()
        ]
        for filename in files:
            if not filename.lower().endswith(".php"):
                continue
            candidate = current_path / filename
            if candidate.is_symlink():
                continue
            source_files.append(candidate)
    return tuple(sorted(source_files, key=lambda path: path.relative_to(root).as_posix()))


class _StaticHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if value is None:
                continue
            normalized = name.casefold()
            if normalized in {"href", "src"}:
                self.references.append((normalized, value.strip()))
            elif normalized in {"action", "formaction"}:
                # A path with a concrete file suffix can be checked like a
                # local asset (for example contact.php). Extensionless form
                # routes are runtime contracts and are intentionally left to
                # the application verification command.
                self.references.append((normalized, value.strip()))
            elif normalized == "srcset":
                for candidate in value.split(","):
                    reference = candidate.strip().split(maxsplit=1)[0]
                    if reference:
                        self.references.append(("srcset", reference))


_CSS_REFERENCE_RE = re.compile(
    r"(?:@import\s+(?:url\(\s*)?|url\(\s*)['\"]?([^'\")\s]+)['\"]?\s*\)?",
    re.IGNORECASE,
)
_JS_REFERENCE_RE = re.compile(
    r"(?:\b(?:import|export)\s+(?:[^\"'\n]*?\s+from\s+)?|\brequire\s*\(|\bimport\s*\()\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)


def _web_files(root: Path) -> tuple[tuple[Path, str], ...]:
    files: list[tuple[Path, str]] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            directory
            for directory in directories
            if directory not in _WEB_IGNORED_DIRECTORIES
            and not (current_path / directory).is_symlink()
        ]
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            suffix = candidate.suffix.casefold()
            if suffix in _HTML_SUFFIXES | _CSS_SUFFIXES | _JS_SUFFIXES:
                files.append((candidate, candidate.relative_to(root).as_posix()))
    return tuple(sorted(files, key=lambda item: item[1]))


def _web_root_prefix(relative: PurePosixPath) -> PurePosixPath:
    parts = relative.parts[:-1]
    for index, part in enumerate(parts):
        if part.casefold() in _WEB_ROOT_NAMES:
            return PurePosixPath(*parts[: index + 1])
    return PurePosixPath()


def _safe_local_reference(
    source_relative: PurePosixPath,
    raw_reference: str,
) -> tuple[PurePosixPath | None, str | None]:
    parsed = urlsplit(raw_reference)
    if parsed.scheme or parsed.netloc:
        return None, None
    path = unquote(parsed.path).replace("\\", "/")
    if not path or path.startswith("#"):
        return None, None
    if path.startswith("/"):
        prefix = _web_root_prefix(source_relative)
        combined = f"{prefix.as_posix()}/{path.lstrip('/')}" if prefix.parts else path.lstrip("/")
    else:
        combined = f"{source_relative.parent.as_posix()}/{path}"
    normalized = PurePosixPath(posixpath.normpath(combined))
    if normalized.is_absolute() or ".." in normalized.parts:
        return None, "path escapes the project root"
    return normalized, None


def _reference_candidates(
    resolved: PurePosixPath,
    raw_reference: str,
    *,
    kind: str,
) -> tuple[PurePosixPath, ...]:
    candidates = [resolved]
    parsed_path = urlsplit(raw_reference).path
    if kind in {"href", "src", "srcset"} and (
        parsed_path.endswith("/") or not PurePosixPath(parsed_path).suffix
    ):
        candidates.extend((resolved / "index.html", resolved / "index.php"))
    if kind == "js" and not resolved.suffix:
        candidates.extend(
            resolved.with_suffix(suffix)
            for suffix in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".json")
        )
        candidates.extend(
            resolved / f"index{suffix}"
            for suffix in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")
        )
    return tuple(dict.fromkeys(candidates))


def _is_external_or_runtime_reference(raw_reference: str, *, kind: str) -> bool:
    parsed = urlsplit(raw_reference)
    if parsed.scheme or parsed.netloc:
        return True
    lowered = raw_reference.casefold().strip()
    if lowered.startswith(("data:", "blob:", "mailto:", "tel:", "javascript:", "about:")):
        return True
    if kind == "css" and lowered.startswith(("var(", "env(")):
        # CSS custom properties are evaluated by the browser at runtime, so
        # the token inside url(var(--asset)) is not a project-relative path.
        return True
    # JavaScript routes and API endpoints are runtime concerns.  Static module
    # imports are always checked, including extensionless relative imports.
    if kind == "js":
        path = parsed.path
        if not path.startswith(("./", "../", "/")):
            return True
        if not PurePosixPath(path).suffix and not path.startswith(("./", "../")):
            return True
    return kind in {"action", "formaction"} and not PurePosixPath(parsed.path).suffix


def _read_static_file(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_STATIC_WEB_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def static_web_diagnostics(
    project_root: str | Path,
    *,
    relative_files: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Check local HTML/CSS/JS references without running application code.

    ``relative_files`` limits inspection to the files selected for the current
    bounded Agent context.  The available-target index still covers the whole
    project, so a selected page can resolve its existing assets without
    rescanning unrelated stylesheets.  Final Verification intentionally calls
    this function without a scope and audits the complete web graph.
    """

    root = Path(project_root).expanduser().resolve()
    web_files = _web_files(root)
    if relative_files is not None:
        scope = {
            PurePosixPath(item.replace("\\", "/")).as_posix()
            for item in relative_files
            if item
        }
        web_files = tuple(item for item in web_files if item[1] in scope)
    if not web_files:
        return ()
    available = {relative for _path, relative in web_files}
    # Include non-web targets such as images and fonts in the index.  The
    # check remains bounded by the same ignored/symlink policy as the web set.
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            directory
            for directory in directories
            if directory not in _WEB_IGNORED_DIRECTORIES
            and not (current_path / directory).is_symlink()
        ]
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_file() and not candidate.is_symlink():
                available.add(candidate.relative_to(root).as_posix())

    errors: list[str] = []
    for source, relative_name in web_files:
        suffix = source.suffix.casefold()
        try:
            oversized = source.stat().st_size > MAX_STATIC_WEB_FILE_BYTES
        except OSError as exc:
            errors.append(f"{relative_name}: file could not be inspected ({exc})")
            continue
        if oversized:
            errors.append(
                f"{relative_name}: file exceeds the {MAX_STATIC_WEB_FILE_BYTES}-byte static-check limit"
            )
            continue
        content = _read_static_file(source)
        if content is None:
            errors.append(f"{relative_name}: file could not be read for static validation")
            continue
        references: list[tuple[str, str]] = []
        if suffix in _HTML_SUFFIXES:
            parser = _StaticHtmlParser()
            try:
                parser.feed(content)
                parser.close()
            except (TypeError, ValueError) as exc:  # pragma: no cover - HTMLParser is permissive
                errors.append(f"{relative_name}: HTML could not be parsed ({exc})")
            references.extend(parser.references)
        elif suffix in _CSS_SUFFIXES:
            references.extend(("css", match.group(1).strip()) for match in _CSS_REFERENCE_RE.finditer(content))
        elif suffix in _JS_SUFFIXES:
            references.extend(("js", match.group(1).strip()) for match in _JS_REFERENCE_RE.finditer(content))
        source_relative = PurePosixPath(relative_name)
        for kind, raw_reference in references:
            if not raw_reference:
                continue
            if raw_reference == "#":
                errors.append(f"{relative_name}: local {kind} target '#' is a placeholder")
                continue
            if raw_reference.startswith("#"):
                continue
            if _is_external_or_runtime_reference(raw_reference, kind=kind):
                continue
            resolved, problem = _safe_local_reference(source_relative, raw_reference)
            if problem:
                errors.append(f"{relative_name}: local {kind} target {raw_reference!r} {problem}")
                continue
            if resolved is None:
                continue
            candidates = _reference_candidates(resolved, raw_reference, kind=kind)
            if not any(candidate.as_posix() in available for candidate in candidates):
                errors.append(
                    f"{relative_name}: local {kind} target {raw_reference!r} was not found"
                )
    return tuple(errors)


def repair_recoverable_static_references(
    project_root: str | Path,
    *,
    relative_files: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Repair only unambiguous duplicate-directory CSS asset references.

    A common import defect is a stylesheet under ``assets/`` referring to
    ``assets/logo.svg``.  The browser resolves that as ``assets/assets/logo``
    even though the actual asset is next to the stylesheet.  This helper fixes
    that narrow, deterministic case in Empy's isolated copy before a provider
    run.  It never creates files, follows symlinks, changes non-CSS files, or
    guesses between multiple targets; unresolved references remain visible to
    Verification as a real failure.

    The return value contains project-relative stylesheet paths that changed.
    """

    root = Path(project_root).expanduser().resolve()
    scope = None
    if relative_files is not None:
        scope = {
            PurePosixPath(item.replace("\\", "/")).as_posix()
            for item in relative_files
            if item
        }
    changed: list[str] = []
    replacements = 0
    for source, relative_name in _web_files(root):
        if source.suffix.casefold() not in _CSS_SUFFIXES:
            continue
        if scope is not None and relative_name not in scope:
            continue
        if len(changed) >= MAX_STATIC_REPAIR_FILES or replacements >= MAX_STATIC_REPAIR_REPLACEMENTS:
            break
        if source.is_symlink() or not source.is_file():
            continue
        content = _read_static_file(source)
        if content is None:
            continue
        source_relative = PurePosixPath(relative_name)
        parent_name = source_relative.parent.name
        if not parent_name:
            continue
        file_changed = False

        def rewrite(
            match: re.Match[str],
            *,
            source_relative: PurePosixPath = source_relative,
            parent_name: str = parent_name,
        ) -> str:
            nonlocal file_changed, replacements
            raw_reference = match.group(1).strip()
            parsed = urlsplit(raw_reference)
            if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
                return match.group(0)
            raw_path = unquote(parsed.path).replace("\\", "/")
            path_parts = list(PurePosixPath(raw_path).parts)
            if path_parts and path_parts[0] == ".":
                path_parts = path_parts[1:]
            if not path_parts or path_parts[0] != parent_name:
                return match.group(0)
            candidate_relative = (source_relative.parent / PurePosixPath(*path_parts[1:])).as_posix()
            candidate = root / candidate_relative
            if (
                not candidate.is_file()
                or candidate.is_symlink()
                or not candidate.resolve().is_relative_to(root)
            ):
                return match.group(0)
            replacement_path = "/".join(path_parts[1:])
            if raw_path.startswith("./"):
                replacement_path = f"./{replacement_path}"
            replacement = replacement_path
            if parsed.query:
                replacement += f"?{parsed.query}"
            if parsed.fragment:
                replacement += f"#{parsed.fragment}"
            if replacement == raw_reference:
                return match.group(0)
            file_changed = True
            replacements += 1
            return match.group(0).replace(raw_reference, replacement, 1)

        rewritten = _CSS_REFERENCE_RE.sub(rewrite, content)
        if not file_changed or rewritten == content:
            continue
        try:
            source.write_text(rewritten, encoding="utf-8")
        except OSError:
            # Leave the original diagnostic in place if the isolated copy is
            # not writable; callers will surface the actual failure.
            continue
        changed.append(relative_name)
    return tuple(changed)


def _static_web_check_command() -> tuple[str, ...]:
    # A frozen PyInstaller executable is the desktop application's GUI entry
    # point, so ``<app> -m empy_studio.verification_pipeline`` is not a valid
    # module invocation.  The app entry point exposes a small, non-GUI static
    # check mode for this isolated subprocess instead.
    if bool(getattr(sys, "frozen", False)):
        return (sys.executable, "--empy-static-web-check")
    return (sys.executable, "-m", "empy_studio.verification_pipeline", "--static-web-check")


def _python_executable() -> str:
    """Select a real Python interpreter for checks launched by a frozen app."""

    if not bool(getattr(sys, "frozen", False)):
        return sys.executable
    for candidate in ("python3", "python"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    # The resulting command will fail with a normal, recorded 127-style
    # verification result rather than recursively starting the GUI binary.
    return "python3"


def _verification_environment() -> dict[str, str]:
    """Return a subprocess environment that also works from a desktop launch."""

    environment = os.environ.copy()
    current_path = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
    for candidate in _COMMON_TOOL_PATHS:
        if candidate.is_dir() and str(candidate) not in current_path:
            current_path.append(str(candidate))
    if current_path:
        environment["PATH"] = os.pathsep.join(current_path)
    # Verification commands run with the project root as their cwd.  During
    # development (and in a portable checkout) that means a relative
    # ``PYTHONPATH=src`` no longer points at Empy's package.  Add the package's
    # absolute source root so the built-in static check and Python checks work
    # before a wheel is installed as well.
    package_root = str(Path(__file__).resolve().parents[1])
    python_path = [item for item in environment.get("PYTHONPATH", "").split(os.pathsep) if item]
    if package_root not in python_path:
        python_path.insert(0, package_root)
    environment["PYTHONPATH"] = os.pathsep.join(python_path)
    return environment


def _verification_category(value: object) -> VerificationCategory:
    if value == "tests":
        return "tests"
    if value == "build":
        return "build"
    if value == "lint":
        return "lint"
    raise ValueError("verification category must be tests, build, or lint")


def _verification_manifest_path(root: Path) -> Path:
    return root / ".empy" / "verification.json"


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _load_verification_manifest(root: Path) -> tuple[VerificationCheck, ...] | None:
    """Load the user contract after applying a bounded, non-executable schema."""

    manifest = _verification_manifest_path(root)
    if not manifest.exists():
        return None
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError(".empy/verification.json must be a regular file")
    try:
        if manifest.stat().st_size > MAX_VERIFICATION_MANIFEST_BYTES:
            raise ValueError(
                f".empy/verification.json exceeds the {MAX_VERIFICATION_MANIFEST_BYTES}-byte limit"
            )
        value = json.loads(
            manifest.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(".empy/verification.json must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f".empy/verification.json is invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise TypeError(".empy/verification.json must contain an object")
    unknown = sorted(set(value) - {"schema_version", "checks"})
    if unknown:
        raise ValueError(
            ".empy/verification.json contains unsupported field(s): "
            + ", ".join(str(item) for item in unknown)
        )
    schema_version = value.get("schema_version", 1)
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError(".empy/verification.json schema_version must be 1")
    raw_checks = value.get("checks", [])
    if not isinstance(raw_checks, list):
        raise TypeError("verification checks must be a list")
    if len(raw_checks) > MAX_VERIFICATION_CHECKS:
        raise ValueError(
            f".empy/verification.json may contain at most {MAX_VERIFICATION_CHECKS} checks"
        )
    checks: list[VerificationCheck] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_checks):
        if not isinstance(item, dict):
            raise TypeError(f"verification check {index + 1} must be an object")
        unknown_check_fields = sorted(set(item) - {"id", "label", "category", "command"})
        if unknown_check_fields:
            raise ValueError(
                f"verification check {index + 1} contains unsupported field(s): "
                + ", ".join(str(field) for field in unknown_check_fields)
            )
        check_id = item.get("id")
        label = item.get("label", check_id)
        command = item.get("command")
        if not isinstance(check_id, str) or _VERIFICATION_ID_RE.fullmatch(check_id) is None:
            raise ValueError(
                f"verification check {index + 1} id must use letters, numbers, ., _, or -"
            )
        if check_id in seen_ids:
            raise ValueError(f"verification check ids must be unique: {check_id}")
        seen_ids.add(check_id)
        if not isinstance(label, str) or not label.strip() or len(label) > 256:
            raise ValueError(f"verification check {check_id} label is invalid")
        if (
            not isinstance(command, list)
            or not command
            or len(command) > MAX_VERIFICATION_COMMAND_PARTS
            or not all(isinstance(part, str) and part and "\x00" not in part for part in command)
            or any(len(part.encode("utf-8")) > MAX_VERIFICATION_COMMAND_PART_BYTES for part in command)
        ):
            raise ValueError(
                f"verification check {check_id} command must be a bounded non-empty string list"
            )
        checks.append(
            VerificationCheck(
                check_id=check_id,
                label=label.strip(),
                category=_verification_category(item.get("category", "tests")),
                command=tuple(command),
            )
        )
    return tuple(checks)


def verification_manifest_fingerprint(root: Path) -> str:
    """Hash the exact custom contract so persisted evidence becomes stale on edits."""

    manifest = _verification_manifest_path(root)
    if not manifest.exists() or manifest.is_symlink() or not manifest.is_file():
        return "missing"
    try:
        if manifest.stat().st_size > MAX_VERIFICATION_MANIFEST_BYTES:
            return "oversized"
        return hashlib.sha256(manifest.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def map_project_verification(detection: ProjectDetection) -> tuple[VerificationCheck, ...]:
    root = detection.effective_verification_root
    project_type = detection.descriptor.project_type
    checks: list[VerificationCheck] = []
    if project_type == "python":
        python = _python_executable()
        checks.extend(
            (
                VerificationCheck("tests", "Python tests", "tests", (python, "-m", "pytest", "-q")),
                VerificationCheck("build", "Python compilation", "build", (python, "-m", "compileall", "-q", "src")),
                VerificationCheck("lint", "Ruff lint", "lint", (python, "-m", "ruff", "check", ".")),
            )
        )
    elif project_type == "laravel":
        checks.append(VerificationCheck("tests", "Laravel tests", "tests", ("php", "artisan", "test")))
        checks.append(VerificationCheck("build", "Composer validation", "build", ("composer", "validate", "--no-check-publish")))
        pint = root / "vendor" / "bin" / "pint"
        if pint.is_file():
            checks.append(VerificationCheck("lint", "Laravel Pint", "lint", (str(pint), "--test")))
    elif project_type == "php":
        if (root / "composer.json").is_file():
            checks.append(
                VerificationCheck(
                    "build",
                    "Composer validation",
                    "build",
                    ("composer", "validate", "--no-check-publish"),
                )
            )
            composer_scripts = _composer_scripts(root)
            # Keep the declared test contract visible even when dependencies
            # are missing.  The preflight diagnostic below stops execution in
            # that case; silently omitting the check made a partial run look
            # like a successful verification.
            if "test" in composer_scripts:
                checks.append(
                    VerificationCheck(
                        "tests",
                        "Composer tests",
                        "tests",
                        ("composer", "--no-interaction", "run-script", "test"),
                    )
                )
        elif (root / "vendor" / "bin" / "phpunit").is_file():
            checks.append(
                VerificationCheck(
                    "tests",
                    "PHPUnit tests",
                    "tests",
                    (str(root / "vendor" / "bin" / "phpunit"),),
                )
            )
        # Composer validation proves only the package manifest.  It must never
        # turn an unimplemented or syntactically broken PHP feature into a
        # green release gate, so syntax-check application sources in every
        # plain-PHP project, with or without Composer metadata.
        for index, source_file in enumerate(_php_source_files(root), start=1):
            relative_path = source_file.relative_to(root).as_posix()
            checks.append(
                VerificationCheck(
                    check_id=f"php-lint-{index}",
                    label=f"PHP syntax · {relative_path}",
                    category="lint",
                    command=("php", "-l", str(source_file)),
                )
            )
    elif project_type == "node":
        scripts = _node_scripts(root)
        node_checks: tuple[tuple[VerificationCategory, str], ...] = (
            ("tests", "test"),
            ("build", "build"),
            ("lint", "lint"),
        )
        for node_category, script in node_checks:
            if script in scripts:
                checks.append(
                    VerificationCheck(
                        check_id=node_category,
                        label=f"npm {script}",
                        category=node_category,
                        command=("npm", "run", script),
                    )
                )
    elif project_type == "rust":
        checks.extend(
            (
                VerificationCheck("tests", "Cargo tests", "tests", ("cargo", "test")),
                VerificationCheck("build", "Cargo build", "build", ("cargo", "build")),
                VerificationCheck("lint", "Cargo clippy", "lint", ("cargo", "clippy", "--", "-D", "warnings")),
            )
        )
    elif project_type == "go":
        checks.extend(
            (
                VerificationCheck("tests", "Go tests", "tests", ("go", "test", "./...")),
                VerificationCheck("build", "Go build", "build", ("go", "build", "./...")),
                VerificationCheck("lint", "Go vet", "lint", ("go", "vet", "./...")),
            )
        )

    manifest_checks = _load_verification_manifest(root)
    if manifest_checks is not None:
        checks = list(manifest_checks)
    if _web_files(root) and not any(item.check_id == "static-web-links" for item in checks):
        checks.append(
            VerificationCheck(
                "static-web-links",
                "Static HTML/CSS/JS links",
                "lint",
                _static_web_check_command(),
            )
        )
    return tuple(checks)


def _verification_diagnostics(detection: ProjectDetection) -> tuple[str, ...]:
    """Report required checks that could not be mapped safely."""

    root = detection.effective_verification_root
    diagnostics: list[str] = []
    if (
        detection.descriptor.project_type in {"php", "laravel"}
        and (root / "composer.json").is_file()
        and (
            detection.descriptor.project_type == "laravel"
            or composer_dependencies_required(root)
        )
    ):
        scripts = _composer_scripts(root)
        if (
            detection.descriptor.project_type == "laravel"
            or "test" in scripts
            or "verify-release" in scripts
        ) and not (root / "vendor" / "autoload.php").is_file():
            diagnostics.append(
                "Composer dependencies are not available in the isolated copy because "
                "vendor/autoload.php is missing. Empy will prepare them from composer.lock "
                "before the Agent and Verification; if Composer or the lockfile is unavailable, "
                "Empy will report that exact blocker instead of skipping the check."
            )
    if detection.descriptor.project_type == "node" and (root / "package.json").is_file():
        scripts = _node_scripts(root)
        if (
            any(name in scripts for name in ("test", "build", "lint"))
            and node_dependencies_required(root)
            and not (root / "node_modules").is_dir()
        ):
            diagnostics.append(
                "Node verification dependencies are not available in the isolated copy because "
                "node_modules is missing. Empy will prepare them from package-lock.json before "
                "the Agent and Verification; if npm or the lockfile is unavailable, Empy will "
                "report that exact blocker instead of skipping the check."
            )
    return tuple(diagnostics)


def verification_preflight(
    detection: ProjectDetection,
    *,
    static_scope: tuple[str, ...] | None = None,
) -> VerificationPreflight:
    """Inspect the verification contract without running project commands.

    Importing a project must surface missing runtime prerequisites before an
    Agent spends tokens on a ticket. This function is deliberately static: it
    does not install dependencies, execute project code, or modify the source
    copy.
    """

    diagnostics: list[str] = []
    try:
        checks = map_project_verification(detection)
    except (OSError, TypeError, ValueError) as exc:
        checks = ()
        diagnostics.append(f"Verification contract could not be read: {exc}")
    try:
        diagnostics.extend(_verification_diagnostics(detection))
    except (OSError, TypeError, ValueError) as exc:
        diagnostics.append(f"Verification prerequisites could not be read: {exc}")
    try:
        static_errors = static_web_diagnostics(
            detection.descriptor.root,
            relative_files=static_scope,
        )
        if static_errors:
            shown = "; ".join(static_errors[:20])
            extra = f"; and {len(static_errors) - 20} more" if len(static_errors) > 20 else ""
            diagnostics.append(f"Static web validation failed: {shown}{extra}")
    except (OSError, TypeError, ValueError) as exc:
        diagnostics.append(f"Static web validation could not be completed: {exc}")
    if not checks:
        diagnostics.append(
            "No safe verification checks were detected for this project. "
            "Configure .empy/verification.json or add a supported test, "
            "build, or lint entry point before export."
        )
    return VerificationPreflight(
        checks=tuple(checks),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def verification_contract_signature(
    detection: ProjectDetection,
    checks: tuple[VerificationCheck, ...] | None = None,
) -> str:
    """Return the contract identity used to produce verification evidence."""

    selected_checks = checks if checks is not None else map_project_verification(detection)
    payload = {
        "engine": "verification-contract-v3",
        "project_type": detection.descriptor.project_type,
        "verification_root": str(detection.effective_verification_root),
        "verification_manifest_sha256": verification_manifest_fingerprint(
            detection.effective_verification_root
        ),
        "checks": [item.to_dict() for item in selected_checks],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verification_staleness_reason(
    report: VerificationReport,
    detection: ProjectDetection,
) -> str | None:
    """Explain why persisted evidence must not be trusted for this run."""

    expected = verification_contract_signature(detection)
    if report.contract_signature != expected:
        return (
            "Stored verification evidence was produced by an older or "
            "different verification contract. Re-run Verification before export."
        )
    return None


class VerificationRuntime:
    """Execute mapped verification checks and stream stdout/stderr evidence."""

    def run(
        self,
        *,
        detection: ProjectDetection,
        evidence_root: Path,
        on_event: Callable[[VerificationEvent], None] | None = None,
        cancel_event: threading.Event | None = None,
        timeout_seconds: float = DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    ) -> VerificationReport:
        if timeout_seconds < 1:
            raise ValueError("verification timeout must be at least one second")
        preflight = verification_preflight(detection)
        checks = preflight.checks
        contract_signature = verification_contract_signature(detection, checks)
        verification_id = uuid.uuid4().hex
        run_root = evidence_root / verification_id
        run_root.mkdir(parents=True, exist_ok=False)
        started_at = _now()
        results: list[VerificationResult] = []
        diagnostics = preflight.diagnostics
        if diagnostics:
            if on_event is not None:
                for diagnostic in diagnostics:
                    on_event(
                        VerificationEvent(
                            _now(),
                            "configuration",
                            "tests",
                            "system",
                            diagnostic,
                        )
                    )
        elif checks:
            for check in checks:
                results.append(
                    self._run_check(
                        check,
                        detection.effective_verification_root,
                        run_root,
                        on_event,
                        cancel_event,
                        timeout_seconds,
                    )
                )
        status: VerificationStatus = (
            "pass"
            if checks and not diagnostics and all(item.status == "pass" for item in results)
            else "fail"
        )
        report = VerificationReport(
            schema_version=1,
            verification_id=verification_id,
            project_root=str(detection.descriptor.root),
            project_type=detection.descriptor.project_type,
            status=status,
            started_at=started_at,
            finished_at=_now(),
            results=tuple(results),
            evidence_path=str(run_root),
            diagnostics=diagnostics,
            verification_root=str(detection.effective_verification_root),
            contract_signature=contract_signature,
        )
        (run_root / "verification-report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report

    def _run_check(
        self,
        check: VerificationCheck,
        cwd: Path,
        run_root: Path,
        on_event: Callable[[VerificationEvent], None] | None,
        cancel_event: threading.Event | None,
        timeout_seconds: float,
    ) -> VerificationResult:
        if cancel_event is not None and cancel_event.is_set():
            raise VerificationCancelled("Verification was cancelled before it started.")
        started_at = _now()
        try:
            process = subprocess.Popen(
                check.command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_verification_environment(),
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            stderr = f"Unable to start verification command: {exc}\n"
            if on_event is not None:
                on_event(VerificationEvent(_now(), check.check_id, check.category, "system", stderr))
            (run_root / f"{check.check_id}.stdout.txt").write_text("", encoding="utf-8")
            (run_root / f"{check.check_id}.stderr.txt").write_text(stderr, encoding="utf-8")
            return VerificationResult(
                check=check,
                status="fail",
                returncode=127,
                stdout="",
                stderr=stderr,
                started_at=started_at,
                finished_at=_now(),
            )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def consume(
            stream: TextIO | None,
            name: Literal["stdout", "stderr"],
            sink: list[str],
        ) -> None:
            if stream is None:
                return
            while True:
                line = stream.readline()
                if line == "":
                    break
                sink.append(line)
                if on_event is not None:
                    on_event(VerificationEvent(_now(), check.check_id, check.category, name, line))

        stdout_thread = threading.Thread(target=consume, args=(process.stdout, "stdout", stdout_lines), daemon=True)
        stderr_thread = threading.Thread(target=consume, args=(process.stderr, "stderr", stderr_lines), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + timeout_seconds
        terminal_error: VerificationCancelled | VerificationTimedOut | None = None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                terminal_error = VerificationCancelled("Verification was cancelled.")
                self._terminate_process(process)
                break
            if time.monotonic() >= deadline:
                terminal_error = VerificationTimedOut(
                    f"Verification exceeded the {timeout_seconds:g}-second timeout."
                )
                self._terminate_process(process)
                break
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
        try:
            returncode = process.wait(timeout=DEFAULT_PROCESS_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill_process(process)
            returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        (run_root / f"{check.check_id}.stdout.txt").write_text(stdout, encoding="utf-8")
        (run_root / f"{check.check_id}.stderr.txt").write_text(stderr, encoding="utf-8")
        if terminal_error is not None:
            raise terminal_error
        return VerificationResult(
            check=check,
            status="pass" if returncode == 0 else "fail",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            finished_at=_now(),
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, AttributeError):
            process.terminate()

    @staticmethod
    def _kill_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, AttributeError):
            process.kill()


def finalize_verification(report: VerificationReport) -> VerificationReport:
    if not report.finalize_allowed:
        raise RuntimeError("Verification failures must be resolved before Finalize")
    return replace(report, finalized_at=_now())


def run_static_web_check(project_root: str | Path = ".") -> int:
    """Run the built-in static web check as a subprocess-safe entry point."""

    errors = static_web_diagnostics(project_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Static HTML/CSS/JS link check passed")
    return 0


def _main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments == ("--static-web-check",):
        return run_static_web_check(Path.cwd())
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised through VerificationRuntime
    raise SystemExit(_main())
