from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final[int] = 1
DEFAULT_MAX_SCAN_FILES: Final[int] = 5_000
DEFAULT_MAX_FILE_BYTES: Final[int] = 1_048_576
DEFAULT_BINARY_PROBE_BYTES: Final[int] = 8_192
DEFAULT_SUMMARY_CHARS: Final[int] = 240
MAX_HINTS: Final[int] = 24

EXCLUDED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".empy",
        ".parcel-cache",
        ".gradle",
        "target",
        "out",
    }
)

SENSITIVE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials",
        "credentials.json",
        "secrets.json",
        "secret.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
        "known_hosts",
    }
)

SENSITIVE_SUFFIXES: Final[tuple[str, ...]] = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
)

GENERATED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
)

TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "",
        ".py",
        ".pyi",
        ".php",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".htm",
        ".xml",
        ".svg",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".md",
        ".rst",
        ".txt",
        ".sql",
        ".sh",
        ".zsh",
        ".bash",
        ".fish",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".erb",
        ".blade.php",
        ".dockerfile",
    }
)

BINARY_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".7z",
        ".a",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dmg",
        ".doc",
        ".docx",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".pdf",
        ".png",
        ".so",
        ".tar",
        ".wasm",
        ".webp",
        ".whl",
        ".xls",
        ".xlsx",
        ".zip",
    }
)


@dataclass(frozen=True)
class ProjectBrainRecord:
    relative_path: str
    sha256: str
    size: int
    mtime_ns: int
    language: str
    imports: tuple[str, ...]
    symbols: tuple[str, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectBrainRecord:
        return cls(
            relative_path=str(data["relative_path"]),
            sha256=str(data["sha256"]),
            size=int(data["size"]),
            mtime_ns=int(data["mtime_ns"]),
            language=str(data.get("language") or "text"),
            imports=tuple(str(item) for item in data.get("imports", ())),
            symbols=tuple(str(item) for item in data.get("symbols", ())),
            summary=str(data.get("summary") or ""),
        )


@dataclass(frozen=True)
class ProjectBrainIndex:
    schema_version: int
    project_root: str
    records: tuple[ProjectBrainRecord, ...]
    changed_paths: tuple[str, ...] = ()
    removed_paths: tuple[str, ...] = ()
    reused_paths: tuple[str, ...] = ()
    skipped_paths: tuple[str, ...] = ()
    scan_limit_reached: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_root": self.project_root,
            "records": [record.to_dict() for record in self.records],
            "changed_paths": list(self.changed_paths),
            "removed_paths": list(self.removed_paths),
            "reused_paths": list(self.reused_paths),
            "skipped_paths": list(self.skipped_paths),
            "scan_limit_reached": self.scan_limit_reached,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectBrainIndex:
        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            project_root=str(data.get("project_root") or ""),
            records=tuple(
                ProjectBrainRecord.from_dict(item)
                for item in data.get("records", ())
                if isinstance(item, dict)
            ),
            changed_paths=tuple(str(item) for item in data.get("changed_paths", ())),
            removed_paths=tuple(str(item) for item in data.get("removed_paths", ())),
            reused_paths=tuple(str(item) for item in data.get("reused_paths", ())),
            skipped_paths=tuple(str(item) for item in data.get("skipped_paths", ())),
            scan_limit_reached=bool(data.get("scan_limit_reached", False)),
        )

    def stats(self) -> dict[str, object]:
        return {
            "source": "local_project_brain_index",
            "file_count": len(self.records),
            "total_bytes": sum(record.size for record in self.records),
            "indexed_files": len(self.records),
            "reused_files": len(self.reused_paths),
            "changed_files": len(self.changed_paths),
            "removed_files": len(self.removed_paths),
            "skipped_files": len(self.skipped_paths),
            "scan_limit_reached": self.scan_limit_reached,
        }

    def record_map(self) -> dict[str, ProjectBrainRecord]:
        return {record.relative_path: record for record in self.records}

    @property
    def files(self) -> tuple[ProjectBrainRecord, ...]:
        """Compatibility alias for callers that used the first index shape."""

        return self.records

    def save(self, path: Path | str) -> None:
        save_project_brain_index(self, path)

    @classmethod
    def load(cls, path: Path | str) -> ProjectBrainIndex:
        return load_project_brain_index(path)


@dataclass(frozen=True)
class ProjectBrainBuildResult:
    index: ProjectBrainIndex
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    reused_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]


def load_project_brain_index(path: Path | str) -> ProjectBrainIndex:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("project brain index must be a JSON object")
    return ProjectBrainIndex.from_dict(data)


def save_project_brain_index(index: ProjectBrainIndex, path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(index.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_project_brain_index(
    root: Path | str,
    *,
    previous: ProjectBrainIndex | None = None,
    max_scan_files: int = DEFAULT_MAX_SCAN_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> ProjectBrainBuildResult:
    if max_scan_files < 1:
        raise ValueError("max_scan_files must be positive")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")

    project_root = Path(root).expanduser().resolve()
    previous_records = previous.record_map() if previous else {}
    indexed_paths: set[str] = set()
    changed_paths: list[str] = []
    reused_paths: list[str] = []
    skipped_paths: list[str] = []
    records: list[ProjectBrainRecord] = []
    scan_limit_reached = False

    for path in _iter_candidate_paths(project_root):
        relative = path.relative_to(project_root).as_posix()
        if len(records) >= max_scan_files:
            scan_limit_reached = True
            skipped_paths.append("./")
            break

        try:
            stat = path.stat()
        except OSError:
            skipped_paths.append(relative)
            continue

        if stat.st_size > max_file_bytes:
            skipped_paths.append(relative)
            continue

        previous_record = previous_records.get(relative)
        if (
            previous_record is not None
            and previous_record.size == stat.st_size
            and previous_record.mtime_ns == stat.st_mtime_ns
        ):
            records.append(previous_record)
            reused_paths.append(relative)
            indexed_paths.add(relative)
            continue

        try:
            record = _build_record(path, relative, stat.st_size, stat.st_mtime_ns)
        except OSError:
            skipped_paths.append(relative)
            continue
        except UnicodeError:
            skipped_paths.append(relative)
            continue
        if record is None:
            skipped_paths.append(relative)
            continue
        records.append(record)
        indexed_paths.add(relative)
        changed_paths.append(relative)

    removed_paths = sorted(set(previous_records) - indexed_paths)
    sorted_records = tuple(sorted(records, key=lambda item: item.relative_path))
    index = ProjectBrainIndex(
        schema_version=SCHEMA_VERSION,
        project_root=str(project_root),
        records=sorted_records,
        changed_paths=tuple(sorted(changed_paths)),
        removed_paths=tuple(removed_paths),
        reused_paths=tuple(sorted(reused_paths)),
        skipped_paths=tuple(sorted(dict.fromkeys(skipped_paths))),
        scan_limit_reached=scan_limit_reached,
    )
    return ProjectBrainBuildResult(
        index=index,
        changed_paths=index.changed_paths,
        removed_paths=index.removed_paths,
        reused_paths=tuple(sorted(reused_paths)),
        skipped_paths=index.skipped_paths,
    )


def build_load_save_project_brain_index(
    root: Path | str,
    index_path: Path | str,
    *,
    max_scan_files: int = DEFAULT_MAX_SCAN_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> ProjectBrainBuildResult:
    destination = Path(index_path)
    previous = load_project_brain_index(destination) if destination.exists() else None
    result = build_project_brain_index(
        root,
        previous=previous,
        max_scan_files=max_scan_files,
        max_file_bytes=max_file_bytes,
    )
    save_project_brain_index(result.index, destination)
    return result


def _iter_candidate_paths(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for directory in sorted(directories):
            directory_path = current_path / directory
            relative = directory_path.relative_to(root).as_posix()
            if _should_skip_path(relative, is_directory=True):
                continue
            if directory_path.is_symlink():
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories

        for filename in sorted(files):
            path = current_path / filename
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                continue
            if _should_skip_path(relative, is_directory=False):
                continue
            yield path


def _should_skip_path(relative_path: str, *, is_directory: bool) -> bool:
    path = Path(relative_path)
    parts = tuple(part.lower() for part in path.parts)
    name = path.name.lower()
    if is_directory:
        return name in EXCLUDED_DIRECTORIES
    if any(part in EXCLUDED_DIRECTORIES for part in parts[:-1]):
        return True
    if _is_sensitive(relative_path):
        return True
    if name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}:
        return True
    if any(name.endswith(suffix) for suffix in GENERATED_SUFFIXES):
        return True
    return path.suffix.lower() in BINARY_EXTENSIONS


def _is_sensitive(relative_path: str) -> bool:
    path = Path(relative_path)
    lowered_parts = tuple(part.lower() for part in path.parts)
    name = path.name.lower()
    if name in SENSITIVE_FILE_NAMES:
        return True
    if name.startswith(".env"):
        return True
    if any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return True
    return any(
        part in {"secrets", "credentials", ".ssh", ".gnupg"}
        for part in lowered_parts[:-1]
    )


def _build_record(
    path: Path,
    relative_path: str,
    size: int,
    mtime_ns: int,
) -> ProjectBrainRecord | None:
    with path.open("rb") as handle:
        probe = handle.read(DEFAULT_BINARY_PROBE_BYTES)
    if _looks_binary(path, probe):
        return None
    raw = path.read_bytes()
    language = _detect_language(path)
    text = raw.decode("utf-8", errors="replace")
    imports, symbols = _extract_hints(language, text)
    return ProjectBrainRecord(
        relative_path=relative_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        size=size,
        mtime_ns=mtime_ns,
        language=language,
        imports=imports,
        symbols=symbols,
        summary=_summarize(relative_path, language, imports, symbols, text),
    )


def _looks_binary(path: Path, probe: bytes) -> bool:
    if b"\x00" in probe:
        return True
    name = path.name.lower()
    if name in {"dockerfile", "makefile", "procfile"}:
        return False
    if name.endswith(".blade.php"):
        return False
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return True
    return suffix not in TEXT_EXTENSIONS


def _detect_language(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == "dockerfile" or suffix == ".dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    if name.endswith(".blade.php"):
        return "php"
    return {
        ".py": "python",
        ".pyi": "python",
        ".php": "php",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".vue": "vue",
        ".svelte": "svelte",
        ".css": "css",
        ".scss": "css",
        ".sass": "css",
        ".less": "css",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".rst": "markdown",
        ".sql": "sql",
        ".sh": "shell",
        ".zsh": "shell",
        ".bash": "shell",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".swift": "swift",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".rb": "ruby",
    }.get(suffix, "text")


def _extract_hints(language: str, text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if language == "python":
        return _extract_python_hints(text)
    imports: set[str] = set()
    symbols: set[str] = set()
    for pattern in (
        r"\bimport\s+(?:[^'\"\n]*?\s+from\s+)?['\"]([^'\"]+)['\"]",
        r"\bfrom\s+['\"]([^'\"]+)['\"]\s+import\b",
        r"\brequire\(['\"]([^'\"]+)['\"]\)",
        r"\buse\s+([A-Za-z_][\w\\]*)\s*;",
        r"\bpackage\s+([A-Za-z_][\w.]*)\s*;",
    ):
        imports.update(match.group(1) for match in re.finditer(pattern, text))
    for pattern in (
        r"\bclass\s+([A-Za-z_][\w]*)",
        r"\binterface\s+([A-Za-z_][\w]*)",
        r"\btrait\s+([A-Za-z_][\w]*)",
        r"\bfunction\s+([A-Za-z_][\w]*)",
        r"\bdef\s+([A-Za-z_][\w]*)",
        r"\bconst\s+([A-Za-z_][\w]*)",
        r"\blet\s+([A-Za-z_][\w]*)",
        r"\bvar\s+([A-Za-z_][\w]*)",
        r"\bexport\s+(?:default\s+)?(?:class|function|const)\s+([A-Za-z_][\w]*)",
    ):
        symbols.update(match.group(1) for match in re.finditer(pattern, text))
    return _clean_hints(imports), _clean_hints(symbols)


def _extract_python_hints(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _extract_hints("text", text)
    imports: set[str] = set()
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add("." * node.level + node.module)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
    return _clean_hints(imports), _clean_hints(symbols)


def _clean_hints(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = {
        value.strip()
        for value in values
        if value and len(value.strip()) <= 120
    }
    return tuple(sorted(cleaned)[:MAX_HINTS])


def _summarize(
    relative_path: str,
    language: str,
    imports: tuple[str, ...],
    symbols: tuple[str, ...],
    text: str,
) -> str:
    parts = [f"{relative_path} ({language})"]
    if symbols:
        parts.append("symbols: " + ", ".join(symbols[:5]))
    if imports:
        parts.append("imports: " + ", ".join(imports[:5]))
    local = _first_meaningful_line(text)
    if local:
        parts.append(local)
    summary = "; ".join(parts)
    return summary[:DEFAULT_SUMMARY_CHARS]


def _first_meaningful_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^(#|//|/\*|\*|<!--|--)\s*", "", line).strip()
        line = re.sub(r"\s*(\*/|-->)$", "", line).strip()
        if line:
            return line[:100]
    return ""
