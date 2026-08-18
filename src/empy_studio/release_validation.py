"""Static validation for files that are about to be shipped in a delta ZIP.

The project being edited is deliberately kept separate from Empy's own source.
This module only reads the isolated project and prevents an export when a
changed HTML page contains a broken local reference or a placeholder link.
External URLs and client-side fragments are not tested here; the project's
own runtime/site checks remain responsible for those semantics.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

_WEB_ROOT_NAMES = frozenset({"public_html", "public", "www", "htdocs"})
_HTML_SUFFIXES = frozenset({".html", ".htm"})


class _ReferenceParser(HTMLParser):
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


def _web_root_prefix(relative: PurePosixPath) -> PurePosixPath:
    parts = relative.parts[:-1]
    for index, part in enumerate(parts):
        if part.casefold() in _WEB_ROOT_NAMES:
            return PurePosixPath(*parts[: index + 1])
    return PurePosixPath()


def _safe_resolved_path(
    source_relative: PurePosixPath,
    raw_path: str,
) -> tuple[PurePosixPath | None, str | None]:
    parsed = urlsplit(raw_path)
    if parsed.scheme or parsed.netloc:
        return None, None
    path = unquote(parsed.path).replace("\\", "/")
    if not path:
        return None, None
    if path.startswith("/"):
        base = _web_root_prefix(source_relative)
        combined = f"{base.as_posix()}/{path.lstrip('/')}" if base.parts else path.lstrip("/")
    else:
        combined = f"{source_relative.parent.as_posix()}/{path}"
    normalized = PurePosixPath(posixpath.normpath(combined))
    if normalized.is_absolute() or ".." in normalized.parts:
        return None, "path escapes the project root"
    return normalized, None


def _candidate_paths(
    resolved: PurePosixPath,
    raw_path: str,
) -> tuple[PurePosixPath, ...]:
    candidates = [resolved]
    parsed_path = urlsplit(raw_path).path
    if parsed_path.endswith("/") or not PurePosixPath(parsed_path).suffix:
        candidates.extend((resolved / "index.html", resolved / "index.php"))
    return tuple(dict.fromkeys(candidates))


def validate_changed_html_links(
    project_root: str | Path,
    changed_members: Iterable[tuple[Path, str]],
) -> tuple[str, ...]:
    """Validate local links in changed HTML files against the full project.

    ``changed_members`` contains files that will be placed in the delta ZIP;
    the complete project file set is used as the target index because the
    deployment archive is intentionally a patch, not a standalone website.
    """

    root = Path(project_root).expanduser().resolve()
    available: set[str] = set()
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            directory
            for directory in directories
            if not (current_path / directory).is_symlink()
        ]
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            available.add(candidate.relative_to(root).as_posix())

    errors: list[str] = []
    for source, relative_name in changed_members:
        relative = PurePosixPath(relative_name)
        if relative.suffix.casefold() not in _HTML_SUFFIXES:
            continue
        try:
            content = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{relative_name}: could not read the changed HTML file ({exc})")
            continue
        parser = _ReferenceParser()
        try:
            parser.feed(content)
            parser.close()
        except (TypeError, ValueError) as exc:  # pragma: no cover - parser is permissive
            errors.append(f"{relative_name}: HTML could not be parsed ({exc})")
            continue
        for kind, raw_value in parser.references:
            if not raw_value or raw_value.startswith("#"):
                if raw_value == "#":
                    errors.append(f"{relative_name}: placeholder {kind}='#' is not a real link")
                continue
            resolved, problem = _safe_resolved_path(relative, raw_value)
            if resolved is None and problem is None:
                continue
            if problem:
                errors.append(f"{relative_name}: {kind}={raw_value!r} {problem}")
                continue
            assert resolved is not None
            if not any(candidate.as_posix() in available for candidate in _candidate_paths(resolved, raw_value)):
                errors.append(
                    f"{relative_name}: local {kind} target {raw_value!r} was not found"
                )

    if errors:
        shown = "; ".join(errors[:20])
        extra = f"; and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise ValueError(f"Local link validation failed: {shown}{extra}")
    return ()
