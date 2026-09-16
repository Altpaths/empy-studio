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
from .planner import (
    AgentRole,
    ExecutionPlan,
    PlanStep,
    classify_intent,
    requests_data_model_changes,
    requests_implementation,
)
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
    ".svelte-kit",
    ".astro",
    ".cache",
    ".turbo",
)

TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "",
        ".py",
        ".pyi",
        ".php",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".astro",
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
        "ux",
        "navigation",
        "nav",
        "menu",
        "header",
        "footer",
        "hero",
        "banner",
        "gallery",
        "form",
        "responsive",
        "mobile",
        "tablet",
        "accessibility",
        "accessible",
        "wcag",
        "a11y",
        "seo",
        "metadata",
        "sitemap",
        "dashboard",
        "chart",
        "graph",
        "table",
        "grid",
        "login",
        "signup",
        "register",
        "cart",
        "checkout",
        "payment",
        "upload",
        "app",
        "tsx",
        "jsx",
        "vue",
        "svelte",
        "astro",
        "index",
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
        "repository",
        "handler",
        "server",
        "auth",
        "authentication",
        "login",
        "signup",
        "password",
        "session",
        "payment",
        "checkout",
        "upload",
        "storage",
        "webhook",
        "database",
        "migration",
        "backend",
    ),
    "coordinator": (
        "app",
        "src",
        "public",
        "api",
        "route",
        "component",
        "template",
        "test",
        "release",
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
        "login",
        "logout",
        "signup",
        "register",
        "password",
        "session",
        "oauth",
        "token",
        "csrf",
        "xss",
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
    {"frontend", "backend", "coordinator", "release"}
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
        ".mjs",
        ".cjs",
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
        ".astro",
    }
)
_FRONTEND_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".css",
        ".html",
        ".htm",
        ".svg",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".scss",
        ".sass",
        ".less",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".astro",
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
        "handler",
        "handlers",
        "repository",
        "repositories",
        "function",
        "functions",
        "src",
        "migration",
        "migrations",
        "schema",
    }
)

MARKET_TASK_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "asset",
        "assets",
        "finance",
        "portfolio",
        "price",
        "prices",
        "quote",
        "market",
        "chart",
        "graph",
        "plot",
        "live",
        "realtime",
        "real-time",
        "دارایی",
        "نمودار",
        "قیمت",
        "بازار",
        "مالی",
        "لحظه",
    }
)

MARKET_MODULE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "asset",
        "assets",
        "finance",
        "portfolio",
        "price",
        "prices",
        "market",
        "quote",
    }
)


def _task_requests_data_model_changes(task_text: str) -> bool:
    """Detect when persistence files are part of the requested implementation.

    A related schema file is normally read-only context.  A ticket that asks
    to persist, record, or store data is different: the writer needs an
    explicit, bounded ownership grant for the matching database/migration/SQL
    file or the runtime will correctly reject the otherwise necessary edit.
    """

    # Keep the ownership decision in the same classifier that builds the
    # execution plan.  In particular, a visual ``table`` must not grant SQL
    # ownership while an explicit schema/persistence request must.
    return requests_data_model_changes(task_text)


def _is_data_model_candidate(relative_path: str) -> bool:
    path = Path(relative_path)
    parts = {part.casefold() for part in path.parts[:-1]}
    name = path.name.casefold()
    return (
        path.suffix.casefold() == ".sql"
        or bool(parts & {"database", "databases", "migration", "migrations", "schema"})
        or "schema" in name
    )


@dataclass(frozen=True)
class ContextPolicy:
    # Keep the default provider context small enough that Empy's local budget
    # remains meaningful even when a provider adds its own tool/system context.
    # Agents can still inspect owned files directly, but the initial prompt
    # must not reproduce an entire application.
    max_files_per_pack: int = 6
    max_bytes_per_file: int = 8_192
    max_total_bytes_per_pack: int = 24_576
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


def _expanded_task_tokens(value: str) -> frozenset[str]:
    """Return bilingual semantic tokens used only for relevance ranking.

    Project filenames are commonly English while the ticket is Persian.  A
    literal intersection therefore ranked unrelated files (for example
    ``about.php``) above ``journey-report.php`` or ``patrol.php``.  Keep the
    expansion deliberately small and product-domain neutral; it only maps
    concepts whose filename equivalents are unambiguous.
    """

    normalized = (
        value.casefold()
        .replace("\u200c", " ")
        .replace("\u200d", " ")
        .replace("\ufeff", " ")
        .replace("ي", "ی")
        .replace("ك", "ک")
    )
    expanded = set(_tokens(normalized))
    aliases: dict[str, tuple[str, ...]] = {
        "گزارش": ("report", "journey", "completion"),
        "مقایسه": ("compare", "comparison"),
        "مقابسه": ("compare", "comparison"),
        "پایش": ("patrol", "monitor", "monitoring", "journey"),
        "دارایی": ("asset", "assets", "finance", "portfolio"),
        "نمودار": ("chart", "graph", "plot", "sparkline"),
        "قیمت": ("price", "prices", "quote", "market"),
        "لحظه": ("live", "realtime", "real-time", "quote"),
        "واقعی": ("real", "live", "market"),
        "جمع": ("collect", "fetch", "gather", "aggregate"),
        "اطلاعات": ("data", "information"),
        "مالی": ("financial", "finance", "analyze"),
        "تحلیل": ("analyze", "analysis"),
        "اتصال": ("api", "client", "service", "integration"),
        "سرویس": ("service", "client", "api"),
        "صفحه": ("page", "view", "index"),
        "خانه": ("home", "index"),
        "سایت": ("site", "website", "web", "homepage"),
        "طراحی": ("design", "redesign", "layout", "ui", "frontend"),
        "بازطراحی": ("redesign", "design", "layout", "ui"),
        "ناوبری": ("navigation", "nav", "menu"),
        "منو": ("menu", "navigation", "nav"),
        "سربرگ": ("header", "navbar", "navigation"),
        "پانوشت": ("footer",),
        "هدر": ("header",),
        "فوتر": ("footer",),
        "هیرو": ("hero", "banner"),
        "بنر": ("banner", "hero"),
        "گالری": ("gallery", "image", "images"),
        "فرم": ("form", "input"),
        "واکنش": ("responsive", "mobile", "tablet"),
        "موبایل": ("mobile", "responsive"),
        "تبلت": ("tablet", "responsive"),
        "دسترسی": ("accessibility", "accessible", "wcag"),
        "پذیری": ("accessibility", "accessible", "wcag"),
        "سئو": ("seo", "metadata", "sitemap"),
        "متادیتا": ("metadata", "meta", "seo"),
        "داشبورد": ("dashboard", "chart", "graph"),
        "جدول": ("table", "grid", "data"),
        "ورود": ("login", "signin", "auth", "authentication"),
        "ثبت": ("register", "signup", "auth"),
        "رمز": ("password", "auth", "security"),
        "پرداخت": ("payment", "checkout", "cart"),
        "درگاه": ("payment", "checkout", "gateway"),
        "سبد": ("cart", "shopping", "checkout"),
        "آپلود": ("upload", "file", "storage"),
        "بارگذاری": ("upload", "file", "storage"),
        "امنیت": ("security", "auth", "permission"),
        "مجوز": ("permission", "authorization", "security"),
    }
    for token in tuple(expanded):
        expanded.update(aliases.get(token, ()))
    if any(
        phrase in normalized
        for phrase in ("ای پی آی", "ای پی ا ی", "ای‌پی‌آی", "api")
    ):
        expanded.update(("api", "client", "service", "integration"))
    if any(
        phrase in normalized
        for phrase in ("هوش مصنوعی", "openai", "avalai", "اول ای آی")
    ):
        expanded.update(("ai", "openai", "avalai", "analyze", "service", "client"))
    return frozenset(expanded)


def _task_requests_homepage(task_text: str) -> bool:
    return classify_intent(task_text).homepage


def _task_requests_frontend_assets(task_text: str) -> bool:
    """Return whether the ticket explicitly calls for styling/assets too."""

    return classify_intent(task_text).frontend_assets


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

    return frozenset(classify_intent(task_text).explicit_files)


def _is_explicit_task_path(
    relative_path: str,
    explicit_paths: frozenset[str],
) -> bool:
    """Match a path that is already normalized to the project root.

    Basename-only references are resolved after candidate discovery, where
    duplicate names can be detected safely.  Keeping this predicate exact
    prevents two ``App.tsx`` files from both receiving an ``explicitly named``
    ownership grant before that disambiguation occurs.
    """

    return relative_path in explicit_paths


def _normalise_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_sensitive(relative_path: str) -> bool:
    return bool(is_sensitive_relative_path(relative_path))


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
    path_tokens = _tokens(
        re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", relative)
        .replace("/", " ")
        .replace(".", " ")
    )
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
    if _is_explicit_task_path(relative, explicit_paths):
        score += 120
        reasons.append("explicitly named in ticket")

    if _task_requests_homepage(task_text):
        verification_root = project.effective_verification_root
        homepage_paths = {
            (verification_root / name).relative_to(project.descriptor.root).as_posix()
            for name in ("index.html", "index.htm", "index.php")
        }
        if relative in homepage_paths:
            score += 100
            reasons.append("detected homepage entry point requested by ticket")

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
    frontend_file = (
        candidate.path.suffix.casefold() in _FRONTEND_SUFFIXES
        and bool(
            path_parts
            & {
                "assets",
                "css",
                "js",
                "frontend",
                "public",
                "scripts",
            }
        )
    )
    if any(keyword in path_tokens for keyword in role_keywords) and not (
        role == "backend" and frontend_file
    ):
        score += 24
        reasons.append(f"{role} path signal")

    if role == "frontend" and task_tokens & MARKET_TASK_TOKENS:
        filename = candidate.path.name.casefold()
        if filename in {"app.js", "app.ts", "chart.js", "chart.ts", "dashboard.js"}:
            score += 54
            reasons.append("market-data task targets interactive asset")
        elif (
            candidate.path.suffix.casefold() in {".js", ".ts"}
            and "assets" in path_parts
            and filename not in {"passkeys.js", "pwa-install.js", "webmcp.js"}
        ):
            score += 30
            reasons.append("market-data task targets asset script")

    if (
        role in {"backend", "coordinator"}
        and task_tokens & MARKET_TASK_TOKENS
        and candidate.path.suffix.casefold() not in _FRONTEND_SUFFIXES
        and candidate.path.suffix.casefold() != ".sql"
    ):
        module_tokens = set(path_tokens)
        if candidate.brain_record is not None:
            module_tokens.update(
                _tokens(
                    " ".join(
                        (
                            candidate.brain_record.language,
                            candidate.brain_record.summary,
                            *candidate.brain_record.imports,
                            *candidate.brain_record.symbols,
                        )
                    )
                )
            )
        module_overlap = module_tokens & MARKET_MODULE_TOKENS
        if module_overlap:
            if module_overlap & {"asset", "assets", "finance", "portfolio"}:
                score += 48
            else:
                score += min(48, len(module_overlap) * 24)
            reasons.append("market-data task matches financial module")

    if (
        role in {"backend", "coordinator"}
        and _task_requests_data_model_changes(task_text)
        and _is_data_model_candidate(relative)
    ):
        score += 72
        reasons.append("ticket requests data model changes")

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

    if len(raw) <= byte_limit:
        included = raw
    else:
        marker = b"\n\n... [Empy omitted the bounded middle section] ...\n\n"
        usable = max(1, byte_limit - len(marker))
        head_size = max(1, (usable * 2) // 3)
        tail_size = max(0, usable - head_size)
        included = raw[:head_size] + marker + (raw[-tail_size:] if tail_size else b"")
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
    stem = candidate.path.stem.casefold()
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
        if suffix in _FRONTEND_SUFFIXES:
            return True
        if project.descriptor.project_type in {"php", "laravel"} and (
            name.endswith(".blade.php")
            or name in {
                "index.php",
                "home.php",
                "homepage.php",
                "login.php",
                "signup.php",
                "register.php",
            }
        ):
            return True
        # A PHP presentation partial in an explicitly named ticket is still
        # a frontend target even when it lives at the project root.
        profile = classify_intent(task_text)
        if profile.frontend and (
            name
            in {
                "header.php",
                "footer.php",
                "navbar.php",
                "menu.php",
                "robots.txt",
                "sitemap.xml",
                "manifest.json",
            }
            or name.endswith(".view.php")
        ):
            return True
        return bool(
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
        backend_path_parts = path_parts & (_BACKEND_PARTS - {"app", "lib", "src"})
        backend_name = any(
            hint in stem
            for hint in (
                "api",
                "auth",
                "controller",
                "database",
                "handler",
                "migration",
                "model",
                "payment",
                "repository",
                "route",
                "schema",
                "server",
                "service",
                "storage",
                "webhook",
            )
        )
        if suffix in _CODE_SUFFIXES and suffix not in {".css", ".html", ".htm"}:
            if suffix not in _FRONTEND_SUFFIXES:
                return True
            if backend_path_parts or backend_name:
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
    return role == "coordinator"


def _explicit_writer_target(
    *,
    project: ProjectDetection,
    role: AgentRole,
    task_text: str,
) -> str | None:
    """Resolve a named file to an exact safe creation/edit target.

    Basename-only references are common in the desktop intake (``App.tsx``
    and ``FinanceService.php``).  Prefer an existing unique match, then place
    a missing source file in the detected conventional source directory.  A
    path containing ``..`` or a sensitive name is never converted into a
    virtual writer target.
    """

    profile = classify_intent(task_text)
    explicit = profile.explicit_files
    if not explicit or role not in WRITING_ROLES:
        return None

    root = project.descriptor.root
    verification_root = project.effective_verification_root
    verification_prefix = ""
    if verification_root != root:
        verification_prefix = verification_root.relative_to(root).as_posix()
    for raw in explicit:
        value = raw.replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.name:
            continue
        suffix = path.suffix.casefold()
        name = path.name.casefold()
        stem = path.stem.casefold()
        frontend_file = (
            suffix in _FRONTEND_SUFFIXES
            or name.endswith(".blade.php")
            or stem
            in {
                "app",
                "index",
                "home",
                "homepage",
                "layout",
                "page",
                "header",
                "footer",
                "navbar",
                "navigation",
                "menu",
                "hero",
                "gallery",
                "dashboard",
                "chart",
                "graph",
                "form",
                "login",
                "signup",
                "register",
                "sitemap",
                "robots",
                "manifest",
            }
        )
        backend_file = (
            suffix in _CODE_SUFFIXES
            and suffix not in _FRONTEND_SUFFIXES
        ) or any(
            hint in stem
            for hint in (
                "service",
                "controller",
                "repository",
                "handler",
                "middleware",
                "model",
                "route",
                "api",
                "server",
                "database",
                "migration",
                "schema",
                "auth",
                "payment",
            )
        )
        if role == "frontend" and not frontend_file:
            continue
        if role == "backend" and not backend_file and not profile.backend:
            continue
        if _is_sensitive(value):
            continue

        exact = root / value
        if exact.is_file() and not exact.is_symlink():
            return value
        verification_exact = verification_root / value
        if (
            verification_root != root
            and verification_exact.is_file()
            and not verification_exact.is_symlink()
        ):
            return verification_exact.relative_to(root).as_posix()

        # A basename can be unqualified while the archive keeps the actual
        # file below public_html/src or resources/views.  Use a unique match;
        # two matches stay ambiguous and fall through to the framework rule.
        if "/" not in value:
            matches = sorted(
                candidate
                for candidate in root.rglob(path.name)
                if candidate.is_file()
                and not candidate.is_symlink()
                and not _is_sensitive(candidate.relative_to(root).as_posix())
            )
            if len(matches) == 1:
                return matches[0].relative_to(root).as_posix()

        if "/" in value:
            if verification_prefix and value != verification_prefix and not value.startswith(
                f"{verification_prefix}/"
            ):
                return f"{verification_prefix}/{value}"
            return value
        if (
            project.descriptor.project_type == "laravel"
            and role == "frontend"
            and (verification_root / "resources" / "views").is_dir()
        ):
            return (
                f"{verification_root.relative_to(root).as_posix()}/resources/views/{value}"
                if verification_root != root
                else f"resources/views/{value}"
            )
        if (verification_root / "src").is_dir() and role in {"frontend", "backend", "coordinator"}:
            prefix = verification_root.relative_to(root).as_posix() if verification_root != root else ""
            return f"{prefix + '/' if prefix else ''}src/{value}"
        prefix = verification_root.relative_to(root).as_posix() if verification_root != root else ""
        return f"{prefix + '/' if prefix else ''}{value}"
    return None


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

    if role not in {"frontend", "backend", "coordinator"}:
        return None
    if not requests_implementation(task_text):
        return None

    root = project.effective_verification_root
    project_type = project.descriptor.project_type
    explicit_target = _explicit_writer_target(
        project=project,
        role=role,
        task_text=task_text,
    )
    if explicit_target is not None:
        return explicit_target
    if role == "frontend":
        if project_type == "laravel" and (root / "resources" / "views").is_dir():
            filename = "resources/views/index.blade.php"
        elif project_type == "node" and (root / "src").is_dir():
            # Prefer the extension already used by a component tree.  A new
            # Node site without one gets a conventional React-compatible
            # source entry instead of an unrelated root HTML file.
            extension = next(
                (
                    candidate.suffix
                    for candidate in sorted((root / "src").rglob("*"))
                    if candidate.is_file()
                    and candidate.suffix.casefold() in {".tsx", ".jsx", ".vue", ".svelte", ".astro"}
                ),
                ".jsx",
            )
            filename = f"src/App{extension}"
        elif project_type == "python" and (root / "templates").is_dir():
            filename = "templates/index.html"
        else:
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


def _market_virtual_writer_targets(
    *,
    project: ProjectDetection,
    role: AgentRole,
    task_text: str,
) -> tuple[str, ...]:
    """Return exact, conventional creation targets for a market-data ticket.

    A market chart often needs a small server endpoint even when the imported
    project does not contain one yet.  Granting the whole verification root
    would let a provider create unrelated files (and was the reason an old
    run accepted an unrequested migration).  Keep the creation contract
    explicit: the endpoint is a single exact path, while existing files still
    require their own ownership records.
    """

    if role != "backend" or not requests_implementation(task_text):
        return ()
    if not (_expanded_task_tokens(task_text) & MARKET_TASK_TOKENS):
        return ()
    if project.descriptor.project_type not in {"php", "laravel"}:
        return ()

    root = project.effective_verification_root
    try:
        prefix = root.relative_to(project.descriptor.root).as_posix()
    except ValueError:
        prefix = ""
    if prefix in {".", "./"}:
        prefix = ""
    relative = f"{prefix}/asset-prices.php" if prefix else "asset-prices.php"
    if (project.descriptor.root / relative).is_file():
        return ()
    return (relative,)


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
    # Recovery plans carry sanitized Verification evidence in one explicitly
    # marked constraint.  Include that evidence in local scoring so a
    # corrective writer receives the exact failing file (for example a CSS
    # asset reference) instead of repeating the original ticket's narrower
    # context.  Ordinary user constraints stay out of task scoring to keep
    # first-pass prompts small and deterministic.
    recovery_context = tuple(
        item
        for item in task.constraints
        if item.startswith(
            (
                "Recovery owner:",
                "Previous Empy verification findings:",
            )
        )
    )
    task_text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
            step.title,
            step.objective,
            *recovery_context,
        )
    )
    task_tokens = _expanded_task_tokens(task_text)

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
    verification_prefix = ""
    if project.effective_verification_root != project.descriptor.root:
        verification_prefix = project.effective_verification_root.relative_to(
            project.descriptor.root
        ).as_posix()
    normalized_explicit_paths = frozenset(
        {
            *explicit_paths,
            *(
                f"{verification_prefix}/{path}"
                for path in explicit_paths
                if verification_prefix
                and not path.startswith(f"{verification_prefix}/")
            ),
        }
    )
    unqualified_names = {
        Path(item).name.casefold()
        for item in explicit_paths
        if "/" not in item
    }
    candidate_by_name: dict[str, list[str]] = {}
    for candidate in candidates:
        candidate_by_name.setdefault(candidate.path.name.casefold(), []).append(candidate.relative_path)
    explicit_candidate_paths = frozenset(
        candidate.relative_path
        for candidate in candidates
        if candidate.relative_path in normalized_explicit_paths
        or (
            candidate.path.name.casefold() in unqualified_names
            and len(candidate_by_name[candidate.path.name.casefold()]) == 1
        )
    )
    if explicit_candidate_paths:
        scored = [
            (
                score + 120,
                relative,
                tuple(dict.fromkeys((*reasons, "explicitly named in ticket"))),
                candidate,
            )
            if relative in explicit_candidate_paths
            else (score, relative, reasons, candidate)
            for score, relative, reasons, candidate in scored
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
    if explicit_paths and step.suggested_agent in (*WRITING_ROLES, "quality"):
        exact = [item for item in scored if item[1] in explicit_candidate_paths]
        if exact:
            scored = exact

    # A writer pack is an edit contract, not a second project scan. Keep only
    # files that this role could actually own, plus a path explicitly named by
    # the user. This prevents frontend tickets from receiving unrelated SQL,
    # migrations, reports, or every file below a broad public_html/ scope.
    if step.suggested_agent in WRITING_ROLES:
        scored = [
            item
            for item in scored
            if item[1] in explicit_candidate_paths
            or _is_writable_candidate_for_role(
                item[3],
                role=step.suggested_agent,
                project=project,
                task_text=task_text,
            )
        ]

    task_requests_implementation = requests_implementation(task_text)
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
                project.descriptor.project_type == "php"
                and _task_requests_homepage(task_text)
                and (project.effective_verification_root / "index.php").is_file()
            )
        )
    )
    should_create_virtual_target = (
        virtual_relative is not None
        and not (project.descriptor.root / virtual_relative).is_file()
        and (
            bool(explicit_paths)
            or (
                frontend_homepage_target
                or (
                    step.suggested_agent != "frontend"
                    and not has_existing_writer_target
                )
            )
        )
    )
    if should_create_virtual_target:
        assert virtual_relative is not None
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
        writable_by_path = {
            candidate.relative_path: candidate
            for candidate in candidates
            if _is_writable_candidate_for_role(
                candidate,
                role=step.suggested_agent,
                project=project,
                task_text=task_text,
            )
        }
        # Pick the highest semantic score.  Alphabetical promotion previously
        # turned about.php into the only owned backend file even when the
        # ticket and Project Brain pointed at report/API modules.
        preferred = next(
            (
                candidate
                for _score, relative, _reasons, candidate in scored
                if relative in writable_by_path
            ),
            None,
        )
        if preferred is None and writable_by_path:
            preferred = writable_by_path[min(writable_by_path)]
        if preferred is not None:
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

    # Dependency context is read-only. Keep exact editing ownership separate
    # from the modules needed to understand an interface or its callers. A
    # persistence ticket is the narrow exception: its matching database/SQL
    # context is an approved implementation surface, not merely a dependency.
    if brain_index is not None and scored:
        primary_paths = explicit_candidate_paths or frozenset((scored[0][1],))
        related = set(brain_index.related_paths(primary_paths))
        scored = [
            (
                score,
                path,
                reasons + ("direct indexed dependency context (read-only)",),
                candidate,
            )
            if (
                path in related
                and path not in primary_paths
                and not (
                    _task_requests_data_model_changes(task_text)
                    and _is_data_model_candidate(path)
                )
            )
            else (score, path, reasons, candidate)
            for score, path, reasons, candidate in scored
        ]
        selected_paths = {item[1] for item in scored}
        for candidate in candidates:
            if (
                candidate.relative_path in related - selected_paths
                and not (
                    _task_requests_data_model_changes(task_text)
                    and _is_data_model_candidate(candidate.relative_path)
                )
            ):
                scored.append((
                    85,
                    candidate.relative_path,
                    ("direct indexed dependency context (read-only)",),
                    candidate,
                ))
        scored.sort(key=lambda item: (
            0 if item[1] in primary_paths else 1,
            0 if item[1] in related else 1,
            -item[0], item[1],
        ))

    virtual_targets: list[ContextFile] = (
        [virtual_target] if virtual_target is not None else []
    )
    for relative in _market_virtual_writer_targets(
        project=project,
        role=step.suggested_agent,
        task_text=task_text,
    ):
        if any(item.relative_path == relative for item in virtual_targets):
            continue
        virtual_targets.append(
            ContextFile(
                relative_path=relative,
                score=88,
                reasons=(
                    "approved market endpoint target is currently missing",
                ),
                size_bytes=0,
                included_bytes=0,
                sha256=hashlib.sha256(b"").hexdigest(),
                truncated=False,
                content="",
            )
        )

    files: list[ContextFile] = virtual_targets
    total_bytes = 0
    writer_pack = step.suggested_agent in WRITING_ROLES
    homepage_writer = (
        step.suggested_agent == "frontend"
        and _task_requests_homepage(task_text)
        and not _task_requests_frontend_assets(task_text)
        and not explicit_paths
    )
    max_files = (
        1
        if homepage_writer or (
            bool(explicit_paths)
            and virtual_target is not None
            and not explicit_candidate_paths
        )
        else min(policy.max_files_per_pack, 3)
        if writer_pack
        else policy.max_files_per_pack
    )
    max_total_bytes = (
        min(policy.max_total_bytes_per_pack, 6_144)
        if homepage_writer
        else min(policy.max_total_bytes_per_pack, 8_192)
        if writer_pack
        else policy.max_total_bytes_per_pack
    )
    max_bytes_per_file = min(policy.max_bytes_per_file, 6_144) if writer_pack else policy.max_bytes_per_file
    for score, _relative, reasons, candidate in scored:
        if len(files) >= max_files:
            break
        remaining = max_total_bytes - total_bytes
        if remaining <= 0:
            break
        byte_limit = min(max_bytes_per_file, remaining)
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
        candidate_count=len(scored) + len(virtual_targets),
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
