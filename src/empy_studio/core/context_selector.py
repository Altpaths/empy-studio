from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from .path_policy import is_sensitive_relative_path
from .planner import IMPLEMENTATION_TERMS, AgentRole, ExecutionPlan, PlanStep
from .project_brain import ProjectBrainIndex, ProjectBrainRecord
from .project_service import ProjectDetection
from .task_intake import ProductTask

DEFAULT_EXCLUDED_DIRECTORIES: Final[tuple[str, ...]] = (
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
)

TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "",
        ".py",
        ".pyi",
        ".php",
        ".js",
        ".jsx",
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

ROLE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "discovery": (
        "readme",
        "manifest",
        "config",
        "architecture",
        "roadmap",
        "package",
        "composer",
        "pyproject",
        "cargo",
        "go.mod",
    ),
    "frontend": (
        "view",
        "views",
        "template",
        "templates",
        "component",
        "components",
        "page",
        "pages",
        "public",
        "asset",
        "assets",
        "style",
        "styles",
        "css",
        "frontend",
        "ui",
    ),
    "backend": (
        "app",
        "api",
        "route",
        "routes",
        "controller",
        "controllers",
        "model",
        "models",
        "service",
        "services",
        "database",
        "migration",
        "backend",
    ),
    "quality": (
        "test",
        "tests",
        "spec",
        "specs",
        "fixture",
        "fixtures",
        "pytest",
        "phpunit",
        "quality",
        "lint",
    ),
    "security": (
        "security",
        "auth",
        "authentication",
        "authorization",
        "permission",
        "permissions",
        "policy",
        "policies",
        "middleware",
    ),
    "release": (
        "release",
        "build",
        "deploy",
        "deployment",
        "docker",
        "workflow",
        "workflows",
        "changelog",
        "version",
    ),
}

TEST_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {"test", "tests", "spec", "specs", "__tests__", "آزمون", "تست"}
)
DOCUMENTATION_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {"docs", "documentation", "مستندات", "راهنما"}
)
DOCUMENTATION_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".md", ".mdx", ".rst", ".adoc"}
)
TEST_CHANGE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "add",
        "change",
        "create",
        "delete",
        "fix",
        "modify",
        "remove",
        "rewrite",
        "update",
        "اضافه",
        "بروزرسان",
        "تغییر",
        "ایجاد",
        "اصلاح",
        "حذف",
        "روزرسانی",
        "ساخت",
        "بهروزرسانی",
    }
)
WRITING_ROLES: Final[frozenset[str]] = frozenset(
    {"frontend", "backend", "security", "release"}
)

_CODE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".c",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
    }
)
_FRONTEND_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".css",
        ".html",
        ".htm",
        ".js",
        ".jsx",
        ".scss",
        ".sass",
        ".less",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
    }
)
_BACKEND_PARTS: Final[frozenset[str]] = frozenset(
    {
        "api",
        "app",
        "backend",
        "controller",
        "controllers",
        "database",
        "lib",
        "model",
        "models",
        "route",
        "routes",
        "server",
        "service",
        "services",
        "src",
    }
)


@dataclass(frozen=True)
class ContextPolicy:
    # Keep the default provider context small enough that Empy's local budget
    # remains meaningful even when a provider adds its own tool/system context.
    # Agents can still inspect owned files directly, but the initial prompt
    # must not reproduce an entire application.
    max_files_per_pack: int = 8
    max_bytes_per_file: int = 16_384
    max_total_bytes_per_pack: int = 65_536
    max_candidate_file_bytes: int = 1_048_576
    max_candidates: int = 2_500
    excluded_directories: tuple[str, ...] = DEFAULT_EXCLUDED_DIRECTORIES

    def validate(self) -> None:
        if self.max_files_per_pack < 1:
            raise ValueError("max_files_per_pack must be positive")
        if self.max_bytes_per_file < 1:
            raise ValueError("max_bytes_per_file must be positive")
        if self.max_total_bytes_per_pack < self.max_bytes_per_file:
            raise ValueError(
                "max_total_bytes_per_pack must allow at least one file"
            )
        if self.max_candidate_file_bytes < self.max_bytes_per_file:
            raise ValueError(
                "max_candidate_file_bytes cannot be smaller than max_bytes_per_file"
            )
        if self.max_candidates < self.max_files_per_pack:
            raise ValueError("max_candidates is too small")


@dataclass(frozen=True)
class ProjectBrain:
    project_root: str
    display_name: str
    project_type: str
    markers: tuple[str, ...]
    package_manager: str | None
    has_git: bool
    has_tests: bool
    summary: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ContextFile:
    relative_path: str
    score: int
    reasons: tuple[str, ...]
    size_bytes: int
    included_bytes: int
    sha256: str
    truncated: bool
    content: str

    def validate(self) -> None:
        if not self.relative_path:
            raise ValueError("context file path cannot be empty")
        if self.score < 1:
            raise ValueError("context file score must be positive")
        if self.included_bytes < 0 or self.size_bytes < 0:
            raise ValueError("context file sizes cannot be negative")
        if self.included_bytes > self.size_bytes:
            raise ValueError("included bytes cannot exceed source size")
        if not self.sha256:
            raise ValueError("context file hash cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ContextExclusion:
    relative_path: str
    reason: str
    protected: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ContextPack:
    pack_id: str
    plan_id: str
    task_id: str
    step_id: str
    agent_role: AgentRole
    objective: str
    files: tuple[ContextFile, ...]
    total_bytes: int
    candidate_count: int

    def validate(self) -> None:
        if not self.pack_id or not self.step_id:
            raise ValueError("context pack identity cannot be empty")
        if self.total_bytes < 0:
            raise ValueError("context pack bytes cannot be negative")
        if self.candidate_count < len(self.files):
            raise ValueError("candidate_count cannot be smaller than selected files")
        measured = sum(item.included_bytes for item in self.files)
        if measured != self.total_bytes:
            raise ValueError("context pack byte count is inconsistent")
        for item in self.files:
            item.validate()

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["files"] = [item.to_dict() for item in self.files]
        return value


@dataclass(frozen=True)
class ContextSelection:
    schema_version: int
    selection_id: str
    plan_id: str
    task_id: str
    project_root: str
    created_at: str
    project_brain: ProjectBrain
    packs: tuple[ContextPack, ...]
    exclusions: tuple[ContextExclusion, ...]
    scanned_candidates: int
    selected_files: int
    selected_bytes: int

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported context-selection schema")
        if not self.selection_id or not self.plan_id or not self.task_id:
            raise ValueError("context selection identity cannot be empty")
        if not self.packs:
            raise ValueError("context selection must contain packs")
        if self.scanned_candidates < 0:
            raise ValueError("scanned candidate count cannot be negative")
        measured_files = sum(len(pack.files) for pack in self.packs)
        measured_bytes = sum(pack.total_bytes for pack in self.packs)
        if measured_files != self.selected_files:
            raise ValueError("selected file count is inconsistent")
        if measured_bytes != self.selected_bytes:
            raise ValueError("selected byte count is inconsistent")
        for pack in self.packs:
            pack.validate()

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["project_brain"] = self.project_brain.to_dict()
        value["packs"] = [pack.to_dict() for pack in self.packs]
        value["exclusions"] = [item.to_dict() for item in self.exclusions]
        return value


@dataclass(frozen=True)
class _Candidate:
    path: Path
    relative_path: str
    size_bytes: int
    brain_record: ProjectBrainRecord | None = None


class _SkipCandidate(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in re.findall(r"[^\W_]+", value, flags=re.UNICODE)
        if len(token) >= 2
    )


def _task_requests_test_changes(task_text: str) -> bool:
    """Return whether the ticket asks the writer to change a test file.

    Merely asking to run tests must keep test files read-only.  This narrower
    signal makes an explicit test-edit requirement visible to the writer while
    preserving the bounded context contract for verification-only tickets.
    """

    normalised = task_text.casefold().replace("\u200c", "")
    tokens = re.findall(r"[^\W_]+", normalised, flags=re.UNICODE)
    for index, token in enumerate(tokens):
        if token not in TEST_CHANGE_ACTIONS:
            continue
        window = tokens[max(0, index - 5) : index + 6]
        if any(item in TEST_PATH_PARTS for item in window):
            return True
    return False


def _task_requests_documentation_changes(task_text: str) -> bool:
    """Return whether documentation is part of the requested change.

    README and documentation files are useful for discovery, but passing them
    to every implementation and quality node adds repeated context without
    helping a code-only ticket.  Keep them available when the ticket actually
    asks for documentation, notes, or a named README/Markdown file.
    """

    normalised = task_text.casefold().replace("\u200c", "")
    documentation_terms = (
        "readme",
        "documentation",
        "document",
        "markdown",
        "docs",
        "changelog",
        "release notes",
        "note",
        "مستند",
        "راهنما",
        "یادداشت",
    )
    return any(term in normalised for term in documentation_terms)


def _explicit_task_paths(task_text: str) -> frozenset[str]:
    """Extract concrete project-relative files named by a ticket.

    This is deliberately conservative: only path-shaped values with a file
    extension are treated as scope. If a named path does not exist, normal
    relevance discovery remains available so a misspelt path cannot hide the
    real implementation surface.
    """

    values: set[str] = set()
    for match in re.finditer(
        r"(?<![\w./-])(?:\.?[\w.-]+/)+[\w.-]+\.[A-Za-z0-9_-]+",
        task_text,
    ):
        value = match.group(0).replace("\\", "/").lstrip("./")
        if value:
            values.add(value)
    return frozenset(values)


def _normalise_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_sensitive(relative_path: str) -> bool:
    return is_sensitive_relative_path(relative_path)


def _looks_textual(path: Path, raw: bytes) -> bool:
    if b"\x00" in raw[:1024]:
        return False
    name = path.name.lower()
    if name in {"dockerfile", "makefile", "procfile"}:
        return True
    if name.endswith(".blade.php"):
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


def _discover_candidates(
    root: Path,
    policy: ContextPolicy,
    brain_index: ProjectBrainIndex | None = None,
) -> tuple[tuple[_Candidate, ...], tuple[ContextExclusion, ...]]:
    if (
        brain_index is not None
        and Path(brain_index.project_root).expanduser().resolve() == root.resolve()
    ):
        return _discover_indexed_candidates(root, policy, brain_index)

    candidates: list[_Candidate] = []
    exclusions: list[ContextExclusion] = []
    excluded_directories = set(policy.excluded_directories)
    brain_records = brain_index.record_map() if brain_index else {}

    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for directory in sorted(directories):
            directory_path = current_path / directory
            relative = _normalise_relative(directory_path, root)
            if directory in excluded_directories:
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative + "/",
                        reason="excluded directory",
                        protected=False,
                    )
                )
                continue
            if directory_path.is_symlink():
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative + "/",
                        reason="symlink directory is not followed",
                        protected=True,
                    )
                )
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories

        for filename in sorted(files):
            path = current_path / filename
            relative = _normalise_relative(path, root)

            if path.is_symlink():
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative,
                        reason="symlink file is not included",
                        protected=True,
                    )
                )
                continue
            if _is_sensitive(relative):
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative,
                        reason="sensitive file rule",
                        protected=True,
                    )
                )
                continue
            try:
                size = path.stat().st_size
            except OSError:
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative,
                        reason="file metadata could not be read",
                        protected=False,
                    )
                )
                continue
            if size > policy.max_candidate_file_bytes:
                exclusions.append(
                    ContextExclusion(
                        relative_path=relative,
                        reason="candidate exceeds maximum file size",
                        protected=False,
                    )
                )
                continue

            candidates.append(
                _Candidate(
                    path=path,
                    relative_path=relative,
                    size_bytes=size,
                    brain_record=brain_records.get(relative),
                )
            )
            if len(candidates) >= policy.max_candidates:
                exclusions.append(
                    ContextExclusion(
                        relative_path="./",
                        reason="candidate scan limit reached",
                        protected=False,
                    )
                )
                return tuple(candidates), tuple(exclusions)

    return tuple(candidates), tuple(exclusions)


def _discover_indexed_candidates(
    root: Path,
    policy: ContextPolicy,
    brain_index: ProjectBrainIndex,
) -> tuple[tuple[_Candidate, ...], tuple[ContextExclusion, ...]]:
    """Use the Project Brain manifest instead of walking the repository again."""

    candidates: list[_Candidate] = []
    exclusions: list[ContextExclusion] = []
    excluded_directories = {item.lower() for item in policy.excluded_directories}

    for relative in sorted(set(brain_index.skipped_paths)):
        if not is_sensitive_relative_path(relative):
            continue
        path = (root / relative).resolve()
        if root not in path.parents or path.is_symlink() or not path.is_file():
            continue
        exclusions.append(
            ContextExclusion(
                relative_path=relative,
                reason="sensitive file rule",
                protected=True,
            )
        )

    for record in brain_index.records:
        relative = record.relative_path
        parts = Path(relative).parts
        if any(part.lower() in excluded_directories for part in parts[:-1]):
            exclusions.append(
                ContextExclusion(
                    relative_path=relative,
                    reason="excluded directory",
                    protected=False,
                )
            )
            continue
        if _is_sensitive(relative):
            exclusions.append(
                ContextExclusion(
                    relative_path=relative,
                    reason="sensitive file rule",
                    protected=True,
                )
            )
            continue

        path = (root / relative).resolve()
        if root not in path.parents or path.is_symlink():
            exclusions.append(
                ContextExclusion(
                    relative_path=relative,
                    reason="indexed path is outside the project or is a symlink",
                    protected=True,
                )
            )
            continue
        try:
            stat = path.stat()
        except OSError:
            exclusions.append(
                ContextExclusion(
                    relative_path=relative,
                    reason="file metadata could not be read",
                    protected=False,
                )
            )
            continue
        if stat.st_size > policy.max_candidate_file_bytes:
            exclusions.append(
                ContextExclusion(
                    relative_path=relative,
                    reason="candidate exceeds maximum file size",
                    protected=False,
                )
            )
            continue

        current_record = (
            record
            if stat.st_size == record.size and stat.st_mtime_ns == record.mtime_ns
            else None
        )
        candidates.append(
            _Candidate(
                path=path,
                relative_path=relative,
                size_bytes=stat.st_size,
                brain_record=current_record,
            )
        )
        if len(candidates) >= policy.max_candidates:
            exclusions.append(
                ContextExclusion(
                    relative_path="./",
                    reason="candidate scan limit reached",
                    protected=False,
                )
            )
            break

    return tuple(candidates), tuple(exclusions)


def _path_matches_likely_scope(
    relative_path: str,
    likely_paths: tuple[str, ...],
) -> bool:
    for raw in likely_paths:
        prefix = raw.strip()
        if prefix in {"", "./", "."}:
            return True
        prefix = prefix.lstrip("./")
        if relative_path == prefix.rstrip("/"):
            return True
        if relative_path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _score_candidate(
    candidate: _Candidate,
    *,
    task_tokens: frozenset[str],
    task_text: str,
    step: PlanStep,
    plan: ExecutionPlan,
    project: ProjectDetection,
    brain_index: ProjectBrainIndex | None = None,
) -> tuple[int, tuple[str, ...]]:
    relative = candidate.relative_path
    path_tokens = _tokens(relative.replace("/", " ").replace(".", " "))
    role = step.suggested_agent
    path_parts = {part.casefold() for part in Path(relative).parts[:-1]}
    documentation_path = (
        Path(relative).suffix.casefold() in DOCUMENTATION_SUFFIXES
        or bool(path_parts & DOCUMENTATION_PATH_PARTS)
        or Path(relative).name.casefold() in {"readme", "readme.txt"}
    )
    if (
        documentation_path
        and role not in {"discovery", "release"}
        and not _task_requests_documentation_changes(task_text)
    ):
        return 0, ()
    score = 0
    reasons: list[str] = []

    explicit_paths = _explicit_task_paths(task_text)
    if relative in explicit_paths:
        score += 120
        reasons.append("explicitly named in ticket")

    overlap = task_tokens & path_tokens
    if overlap:
        points = min(35, len(overlap) * 7)
        score += points
        reasons.append("task terms match path")

    if _path_matches_likely_scope(relative, plan.likely_paths):
        score += 28
        reasons.append("inside approved likely scope")

    marker_files = {
        item.rstrip("/")
        for item in project.markers
    }
    if relative in marker_files:
        score += 35
        reasons.append("project marker")

    lowered = relative.lower()
    role_keywords = ROLE_KEYWORDS.get(role, ())
    if any(keyword in path_tokens for keyword in role_keywords):
        score += 24
        reasons.append(f"{role} path signal")

    if (
        role in WRITING_ROLES
        and _task_requests_test_changes(task_text)
        and any(part in TEST_PATH_PARTS for part in path_tokens)
    ):
        score += 42
        reasons.append("ticket explicitly requests test changes")

    if role == "discovery":
        if Path(relative).name.lower() in {
            "readme.md",
            "readme.rst",
            "pyproject.toml",
            "package.json",
            "composer.json",
            "cargo.toml",
            "go.mod",
            "makefile",
            "dockerfile",
        }:
            score += 30
            reasons.append("project orientation file")
    elif role == "quality":
        if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in path_tokens):
            score += 35
            reasons.append("verification file")
        if Path(relative).name.lower() in {
            "pyproject.toml",
            "pytest.ini",
            "phpunit.xml",
            "phpunit.xml.dist",
            "package.json",
        }:
            score += 20
            reasons.append("quality configuration")
    elif (
        role == "release"
        and relative.startswith(".github/workflows/")
    ):
        score += 35
        reasons.append("release workflow")

    suffix = candidate.path.suffix.lower()
    if suffix in TEXT_EXTENSIONS or candidate.path.name.lower() in {
        "dockerfile",
        "makefile",
        "procfile",
    }:
        score += 4

    if candidate.brain_record is not None:
        score += 6
        reasons.append("project brain indexed file")
        hint_text = " ".join(
            (
                candidate.brain_record.language,
                candidate.brain_record.summary,
                *candidate.brain_record.imports,
                *candidate.brain_record.symbols,
            )
        )
        hint_overlap = task_tokens & _tokens(hint_text)
        if hint_overlap:
            score += min(45, len(hint_overlap) * 9)
            reasons.append("indexed imports or symbols match task")

    if brain_index is not None and relative in brain_index.changed_paths:
        score += 30
        reasons.append("changed in project brain")

    if lowered.startswith("docs/") and role not in {"discovery", "release"}:
        score = max(0, score - 10)

    return score, tuple(dict.fromkeys(reasons))


def _read_context_file(
    candidate: _Candidate,
    *,
    score: int,
    reasons: tuple[str, ...],
    byte_limit: int,
) -> ContextFile:
    try:
        raw = candidate.path.read_bytes()
    except OSError as exc:
        raise _SkipCandidate("file content could not be read") from exc

    if not _looks_textual(candidate.path, raw):
        raise _SkipCandidate("binary or unsupported file")

    included = raw[:byte_limit]
    content = included.decode("utf-8", errors="replace")
    return ContextFile(
        relative_path=candidate.relative_path,
        score=score,
        reasons=reasons or ("bounded fallback context",),
        size_bytes=len(raw),
        included_bytes=len(included),
        sha256=hashlib.sha256(raw).hexdigest(),
        truncated=len(raw) > len(included),
        content=content,
    )


def _is_writable_candidate_for_role(
    candidate: _Candidate,
    *,
    role: AgentRole,
    project: ProjectDetection,
    task_text: str,
) -> bool:
    """Return whether a safe source file can give a writer a real target.

    Relevance scoring is intentionally conservative, but a writer must still
    receive at least one target.  On large imported sites a low-scoring PHP
    entry point can otherwise fall outside the four-file context cap while
    unrelated assets fill the pack.  This helper is only a final bounded
    fallback; it never includes sensitive paths or dependency directories.
    """

    relative = candidate.relative_path
    if _is_sensitive(relative):
        return False
    path_parts = {part.casefold() for part in Path(relative).parts[:-1]}
    suffix = candidate.path.suffix.casefold()
    name = candidate.path.name.casefold()
    if (
        path_parts & TEST_PATH_PARTS
        and not _task_requests_test_changes(task_text)
    ):
        return False
    if (
        path_parts & DOCUMENTATION_PATH_PARTS
        and not _task_requests_documentation_changes(task_text)
    ):
        return False
    if role == "frontend":
        return suffix in _FRONTEND_SUFFIXES or bool(
            path_parts
            & {
                "public",
                "assets",
                "component",
                "components",
                "page",
                "pages",
                "template",
                "templates",
                "view",
                "views",
            }
        )
    if role == "backend":
        if suffix in _CODE_SUFFIXES and suffix not in {".css", ".html", ".htm"}:
            return True
        if project.descriptor.project_type in {"php", "laravel"} and name in {"index.php", "artisan"}:
            return True
        if path_parts & _BACKEND_PARTS and suffix in TEXT_EXTENSIONS:
            return True
        return _task_requests_documentation_changes(task_text) and suffix in DOCUMENTATION_SUFFIXES
    if role == "security":
        return bool(path_parts & {"auth", "middleware", "permissions", "policies", "security"})
    if role == "release":
        return (
            relative.startswith(".github/workflows/")
            or name in {"pyproject.toml", "package.json", "composer.json", "cargo.toml", "go.mod", "dockerfile", "changelog.md"}
            or ("release" in path_parts and suffix in TEXT_EXTENSIONS)
        )
    return False


def _virtual_writer_target(
    *,
    project: ProjectDetection,
    role: AgentRole,
    task_text: str,
) -> str | None:
    """Choose a deterministic, safe creation target when a role has no file.

    This is used only for an implementation request and only for conventional
    application entry/source files.  The target is placed under the detected
    verification root, while the archive layout remains rooted at the
    imported project root.
    """

    if role not in {"frontend", "backend"}:
        return None
    if not any(term in task_text.casefold() for term in IMPLEMENTATION_TERMS):
        return None

    root = project.effective_verification_root
    project_type = project.descriptor.project_type
    if role == "frontend":
        filename = "index.html"
    elif project_type in {"php", "laravel"}:
        filename = "src/index.php" if (root / "src").is_dir() else "index.php"
    elif project_type == "python":
        filename = "src/main.py" if (root / "src").is_dir() else "main.py"
    elif project_type == "node":
        filename = "src/index.js" if (root / "src").is_dir() else "index.js"
    elif project_type == "rust":
        filename = "src/main.rs"
    elif project_type == "go":
        filename = "main.go"
    else:
        filename = "src/main.py" if (root / "src").is_dir() else "main.py"

    try:
        prefix = root.relative_to(project.descriptor.root).as_posix()
    except ValueError:
        prefix = ""
    if prefix in {".", "./"}:
        prefix = ""
    return f"{prefix}/{filename}" if prefix else filename


def _project_brain(project: ProjectDetection) -> ProjectBrain:
    descriptor = project.descriptor
    summary_parts = [
        f"{descriptor.display_name} is detected as {descriptor.project_type}.",
    ]
    if project.package_manager:
        summary_parts.append(f"Package manager: {project.package_manager}.")
    summary_parts.append(
        "Tests are present." if project.has_tests else "No conventional test directory was detected."
    )
    return ProjectBrain(
        project_root=str(descriptor.root),
        display_name=descriptor.display_name,
        project_type=descriptor.project_type,
        markers=project.markers,
        package_manager=project.package_manager,
        has_git=project.has_git,
        has_tests=project.has_tests,
        summary=" ".join(summary_parts),
    )


def _build_pack(
    *,
    step: PlanStep,
    task: ProductTask,
    plan: ExecutionPlan,
    project: ProjectDetection,
    candidates: tuple[_Candidate, ...],
    policy: ContextPolicy,
    exclusions: list[ContextExclusion],
    brain_index: ProjectBrainIndex | None = None,
) -> ContextPack:
    task_text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
            step.title,
            step.objective,
        )
    )
    task_tokens = _tokens(task_text)

    scored: list[tuple[int, str, tuple[str, ...], _Candidate]] = []
    for candidate in candidates:
        score, reasons = _score_candidate(
            candidate,
            task_tokens=task_tokens,
            task_text=task_text,
            step=step,
            plan=plan,
            project=project,
            brain_index=brain_index,
        )
        if score > 0:
            scored.append((score, candidate.relative_path, reasons, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))

    # When the user names an existing file, passing a broad directory pack to
    # every node is wasteful and makes the provider rediscover the same scope.
    # Keep exact named files for implementation/quality nodes. Discovery and
    # ambiguous tickets retain the normal scored scope.
    explicit_paths = _explicit_task_paths(task_text)
    if explicit_paths and step.suggested_agent in (*WRITING_ROLES, "quality"):
        exact = [item for item in scored if item[1] in explicit_paths]
        if exact:
            scored = exact

    task_requests_implementation = any(
        term in task_text.casefold()
        for term in IMPLEMENTATION_TERMS
    )
    virtual_target: ContextFile | None = None
    virtual_relative = _virtual_writer_target(
        project=project,
        role=step.suggested_agent,
        task_text=task_text,
    ) if task_requests_implementation else None
    has_existing_writer_target = any(
        _is_writable_candidate_for_role(
            candidate,
            role=step.suggested_agent,
            project=project,
            task_text=task_text,
        )
        for candidate in candidates
    ) if step.suggested_agent in WRITING_ROLES else False
    frontend_homepage_target = (
        step.suggested_agent == "frontend"
        and (
            not has_existing_writer_target
            or (
                project.descriptor.project_type in {"php", "laravel"}
                and (project.effective_verification_root / "index.php").is_file()
            )
        )
    )
    should_create_virtual_target = (
        virtual_relative is not None
        and not (project.descriptor.root / virtual_relative).is_file()
        and (
            frontend_homepage_target
            or (
                step.suggested_agent != "frontend"
                and not has_existing_writer_target
            )
        )
    )
    if should_create_virtual_target:
        virtual_target = ContextFile(
            relative_path=virtual_relative,
            score=60,
            reasons=(
                f"approved {step.suggested_agent} target is currently missing",
            ),
            size_bytes=0,
            included_bytes=0,
            sha256=hashlib.sha256(b"").hexdigest(),
            truncated=False,
            content="",
        )

    # Promote one real role-compatible file into the bounded pack.  The
    # previous relevance-only ordering could spend all four slots on assets
    # and documentation, leaving a backend node with read-only context and
    # causing graph construction to fail after the user had approved the
    # ticket.  Promotion is deterministic and does not broaden the candidate
    # scan or expose protected files.
    if step.suggested_agent in WRITING_ROLES:
        writable_candidates = sorted(
            (
                candidate
                for candidate in candidates
                if _is_writable_candidate_for_role(
                    candidate,
                    role=step.suggested_agent,
                    project=project,
                    task_text=task_text,
                )
            ),
            key=lambda candidate: candidate.relative_path,
        )
        if writable_candidates:
            preferred = writable_candidates[0]
            for index, item in enumerate(scored):
                if item[1] != preferred.relative_path:
                    continue
                score, relative, reasons, candidate = item
                scored[index] = (
                    max(score, 90),
                    relative,
                    tuple(dict.fromkeys((*reasons, "guaranteed writer scope"))),
                    candidate,
                )
                break
            else:
                fallback_score, fallback_reasons = _score_candidate(
                    preferred,
                    task_tokens=task_tokens,
                    task_text=task_text,
                    step=step,
                    plan=plan,
                    project=project,
                    brain_index=brain_index,
                )
                scored.append(
                    (
                        max(90, fallback_score),
                        preferred.relative_path,
                        tuple(dict.fromkeys((*fallback_reasons, "guaranteed writer scope"))),
                        preferred,
                    )
                )
            scored.sort(key=lambda item: (-item[0], item[1]))

    files: list[ContextFile] = [virtual_target] if virtual_target is not None else []
    total_bytes = 0
    for score, _relative, reasons, candidate in scored:
        if len(files) >= policy.max_files_per_pack:
            break
        remaining = policy.max_total_bytes_per_pack - total_bytes
        if remaining <= 0:
            break
        byte_limit = min(policy.max_bytes_per_file, remaining)
        try:
            context_file = _read_context_file(
                candidate,
                score=score,
                reasons=reasons,
                byte_limit=byte_limit,
            )
        except _SkipCandidate as exc:
            exclusions.append(
                ContextExclusion(
                    relative_path=candidate.relative_path,
                    reason=exc.reason,
                    protected=False,
                )
            )
            continue
        files.append(context_file)
        total_bytes += context_file.included_bytes

    pack_seed = json.dumps(
        {
        "plan_id": plan.plan_id,
        "step_id": step.step_id,
        "files": [item.sha256 for item in files],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    pack = ContextPack(
        pack_id=hashlib.sha256(pack_seed).hexdigest()[:20],
        plan_id=plan.plan_id,
        task_id=task.task_id,
        step_id=step.step_id,
        agent_role=step.suggested_agent,
        objective=step.objective,
        files=tuple(files),
        total_bytes=total_bytes,
        candidate_count=len(scored) + (1 if virtual_target is not None else 0),
    )
    pack.validate()
    return pack


def build_context_selection(
    *,
    task: ProductTask,
    project: ProjectDetection,
    plan: ExecutionPlan,
    policy: ContextPolicy | None = None,
    brain_index: ProjectBrainIndex | None = None,
) -> ContextSelection:
    task.validate()
    project.descriptor.validate()
    plan.validate()
    selected_policy = policy or ContextPolicy()
    selected_policy.validate()

    project_root = project.descriptor.root
    if plan.status != "approved":
        raise ValueError("context selection requires an approved plan")
    if plan.task_id != task.task_id:
        raise ValueError("plan and task IDs do not match")
    if Path(plan.project_root).expanduser().resolve() != project_root:
        raise ValueError("plan and project roots do not match")
    if Path(task.project_root).expanduser().resolve() != project_root:
        raise ValueError("task and project roots do not match")

    candidates, initial_exclusions = _discover_candidates(
        project_root,
        selected_policy,
        brain_index=brain_index,
    )
    exclusions = list(initial_exclusions)
    packs = tuple(
        _build_pack(
            step=step,
            task=task,
            plan=plan,
            project=project,
            candidates=candidates,
            policy=selected_policy,
            exclusions=exclusions,
            brain_index=brain_index,
        )
        for step in plan.steps
    )

    identity_payload = json.dumps(
        {
            "plan_id": plan.plan_id,
            "packs": [pack.pack_id for pack in packs],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    selection = ContextSelection(
        schema_version=1,
        selection_id=hashlib.sha256(identity_payload).hexdigest()[:20],
        plan_id=plan.plan_id,
        task_id=task.task_id,
        project_root=str(project_root),
        created_at=_utc_now(),
        project_brain=_project_brain(project),
        packs=packs,
        exclusions=tuple(
            sorted(
                {
                    (item.relative_path, item.reason, item.protected): item
                    for item in exclusions
                }.values(),
                key=lambda item: (item.relative_path, item.reason),
            )
        ),
        scanned_candidates=len(candidates),
        selected_files=sum(len(pack.files) for pack in packs),
        selected_bytes=sum(pack.total_bytes for pack in packs),
    )
    selection.validate()
    return selection
