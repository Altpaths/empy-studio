from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from empy_studio.core import (
    ContextSelection,
    ExecutionPlan,
    ProductTask,
    ProjectDetection,
    TokenBudget,
    build_context_selection,
    estimate_tokens,
)

SAFE_EXCLUDED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
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

SAFE_TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "",
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".scss",
        ".html",
        ".htm",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".md",
        ".rst",
        ".txt",
        ".sql",
        ".sh",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rb",
        ".php",
        ".xml",
        ".svg",
    }
)

MAX_SAFE_FULL_CONTEXT_BYTES: Final[int] = 1_048_576
ESTIMATE_SOURCE: Final[str] = "provider_neutral_local_estimate"


@dataclass(frozen=True)
class ProjectBrainFile:
    relative_path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectBrainIndex:
    schema_version: int
    project_id: str
    display_name: str
    project_type: str
    markers: tuple[str, ...]
    package_manager: str | None
    has_git: bool
    has_tests: bool
    indexed_at: str
    files: tuple[ProjectBrainFile, ...]
    skipped_files: int
    source: str = "local_project_brain_index"

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    def stats(self) -> dict[str, object]:
        return {
            "source": self.source,
            "display_name": self.display_name,
            "project_type": self.project_type,
            "markers": list(self.markers),
            "package_manager": self.package_manager,
            "has_git": self.has_git,
            "has_tests": self.has_tests,
            "indexed_at": self.indexed_at,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "skipped_files": self.skipped_files,
        }

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["files"] = [item.to_dict() for item in self.files]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProjectBrainIndex:
        if int(value["schema_version"]) != 1:
            raise ValueError("unsupported project-brain-index schema")
        raw_files = value.get("files", [])
        if not isinstance(raw_files, list):
            raise TypeError("project-brain-index files must be a list")
        return cls(
            schema_version=1,
            project_id=str(value["project_id"]),
            display_name=str(value["display_name"]),
            project_type=str(value["project_type"]),
            markers=tuple(str(item) for item in value.get("markers", ())),
            package_manager=(
                str(value["package_manager"])
                if value.get("package_manager") is not None
                else None
            ),
            has_git=bool(value["has_git"]),
            has_tests=bool(value["has_tests"]),
            indexed_at=str(value["indexed_at"]),
            files=tuple(
                ProjectBrainFile(
                    relative_path=str(item["relative_path"]),
                    size_bytes=int(item["size_bytes"]),
                    sha256=str(item["sha256"]),
                )
                for item in raw_files
                if isinstance(item, dict)
            ),
            skipped_files=int(value.get("skipped_files", 0)),
            source=str(value.get("source", "local_project_brain_index")),
        )


@dataclass(frozen=True)
class BenchmarkResult:
    candidate_files: tuple[str, ...]
    selected_files: tuple[str, ...]
    full_context_estimate_tokens: int
    bounded_context_estimate_tokens: int
    saved_tokens: int
    savings_percentage: float
    source_estimate: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_files": list(self.candidate_files),
            "selected_files": list(self.selected_files),
            "full_context_estimate_tokens": self.full_context_estimate_tokens,
            "bounded_context_estimate_tokens": self.bounded_context_estimate_tokens,
            "saved_tokens": self.saved_tokens,
            "savings_percentage": self.savings_percentage,
            "source_estimate": self.source_estimate,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    if any(part in SAFE_EXCLUDED_DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1].casefold() if parts else relative_path.casefold()
    return name in SENSITIVE_FILE_NAMES or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def _looks_textual(path: Path, data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    return path.suffix.casefold() in SAFE_TEXT_EXTENSIONS


def _safe_files(project_root: Path) -> tuple[tuple[ProjectBrainFile, ...], int]:
    files: list[ProjectBrainFile] = []
    skipped = 0
    for path in sorted(project_root.rglob("*"), key=lambda item: item.relative_to(project_root).as_posix()):
        if not path.is_file():
            continue
        relative_path = path.relative_to(project_root).as_posix()
        if _is_sensitive(relative_path):
            skipped += 1
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            skipped += 1
            continue
        if not _looks_textual(path, raw):
            skipped += 1
            continue
        files.append(
            ProjectBrainFile(
                relative_path=relative_path,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(files), skipped


def build_project_brain_index(
    *,
    project_id: str,
    project: ProjectDetection,
) -> ProjectBrainIndex:
    files, skipped = _safe_files(project.descriptor.root)
    return ProjectBrainIndex(
        schema_version=1,
        project_id=project_id,
        display_name=project.descriptor.display_name,
        project_type=project.descriptor.project_type,
        markers=project.markers,
        package_manager=project.package_manager,
        has_git=project.has_git,
        has_tests=project.has_tests,
        indexed_at=_utc_now(),
        files=files,
        skipped_files=skipped,
    )


def load_project_brain_index(path: str | Path) -> ProjectBrainIndex:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("project-brain-index root must be an object")
    return ProjectBrainIndex.from_dict(value)


def save_project_brain_index(index: ProjectBrainIndex, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(index.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_load_save_project_brain_index(
    *,
    project_id: str,
    project: ProjectDetection,
    path: str | Path,
) -> ProjectBrainIndex:
    target = Path(path)
    if target.is_file():
        try:
            index = load_project_brain_index(target)
            current_files, skipped = _safe_files(project.descriptor.root)
            if (
                index.project_id == project_id
                and index.files == current_files
                and index.skipped_files == skipped
            ):
                return index
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            pass
    index = build_project_brain_index(project_id=project_id, project=project)
    save_project_brain_index(index, target)
    return index


def _read_for_estimate(root: Path, relative_path: str) -> str:
    path = (root / relative_path).resolve()
    if root not in path.parents and path != root:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if not _looks_textual(path, raw):
        return ""
    return raw[:MAX_SAFE_FULL_CONTEXT_BYTES].decode("utf-8", errors="replace")


def _selected_files(selection: ContextSelection) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.relative_path
                for pack in selection.packs
                for item in pack.files
            }
        )
    )


def _estimate_full_context(
    *,
    task: ProductTask,
    project: ProjectDetection,
    plan: ExecutionPlan,
    brain_index: ProjectBrainIndex,
) -> int:
    root = project.descriptor.root
    task_text = "\n".join(
        (
            task.title,
            task.objective,
            *task.requirements,
            *task.constraints,
            *task.definition_of_done,
        )
    )
    total = 0
    for step in plan.steps:
        total += estimate_tokens(f"{task_text}\n{step.title}\n{step.objective}")
        for item in brain_index.files:
            total += estimate_tokens(item.relative_path)
            total += estimate_tokens(_read_for_estimate(root, item.relative_path))
    return total


def run_local_benchmark(
    *,
    task: ProductTask,
    project: ProjectDetection,
    plan: ExecutionPlan,
    brain_index: ProjectBrainIndex,
    selection: ContextSelection | None = None,
    budget: TokenBudget | None = None,
) -> BenchmarkResult:
    task.validate()
    project.descriptor.validate()
    plan.validate()
    bounded_selection = selection or build_context_selection(
        task=task,
        project=project,
        plan=plan,
    )
    bounded_estimate = (
        budget.estimated_context_tokens
        if budget is not None and budget.selection_id == bounded_selection.selection_id
        else sum(
            estimate_tokens(pack.objective)
            + sum(
                estimate_tokens(file.relative_path)
                + estimate_tokens(" ".join(file.reasons))
                + estimate_tokens(file.content)
                for file in pack.files
            )
            for pack in bounded_selection.packs
        )
    )
    raw_full_estimate = _estimate_full_context(
        task=task,
        project=project,
        plan=plan,
        brain_index=brain_index,
    )
    full_estimate = max(raw_full_estimate, bounded_estimate)
    saved = max(0, full_estimate - bounded_estimate)
    percentage = round((saved / full_estimate * 100.0), 2) if full_estimate else 0.0
    return BenchmarkResult(
        candidate_files=tuple(item.relative_path for item in brain_index.files),
        selected_files=_selected_files(bounded_selection),
        full_context_estimate_tokens=full_estimate,
        bounded_context_estimate_tokens=bounded_estimate,
        saved_tokens=saved,
        savings_percentage=percentage,
        source_estimate=ESTIMATE_SOURCE,
    )
