from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

ReviewDecision = Literal["pending", "accepted", "reverted"]
ReviewStatus = Literal["pending", "complete"]
ChangeKind = Literal["added", "modified", "deleted", "renamed", "unmerged", "unknown"]

_REVIEW_EXCLUDED_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__MACOSX",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "vendor",
        "venv",
    }
)
_REVIEW_EXCLUDED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")


def _reviewable_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return False
    return not any(
        part in _REVIEW_EXCLUDED_NAMES
        or part.startswith(".env.")
        or part.lower().endswith(_REVIEW_EXCLUDED_SUFFIXES)
        for part in path.parts
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(message)
    return result


def _safe_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes project root: {relative_path}")
    return candidate


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _change_kind(code: str) -> ChangeKind:
    if "U" in code or code in {"AA", "DD"}:
        return "unmerged"
    if "R" in code or "C" in code:
        return "renamed"
    if "A" in code or code == "??":
        return "added"
    if "D" in code:
        return "deleted"
    if "M" in code or "T" in code:
        return "modified"
    return "unknown"


def _readable_untracked_diff(path: Path, relative_path: str) -> tuple[str, bool]:
    content = path.read_bytes()
    if b"\x00" in content:
        return f"Binary file added: {relative_path}\n", True
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"Binary file added: {relative_path}\n", True
    lines = text.splitlines(keepends=True)
    empty_lines: tuple[str, ...] = ()
    diff = difflib.unified_diff(
        empty_lines,
        lines,
        fromfile="/dev/null",
        tofile=f"b/{relative_path}",
        lineterm="\n",
    )
    return "".join(diff), False


@dataclass(frozen=True)
class ReviewFile:
    relative_path: str
    git_status: str
    change_kind: ChangeKind
    diff_text: str
    is_binary: bool
    current_sha256: str | None
    original_path: str | None = None
    decision: ReviewDecision = "pending"
    decided_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "git_status": self.git_status,
            "change_kind": self.change_kind,
            "diff_text": self.diff_text,
            "is_binary": self.is_binary,
            "current_sha256": self.current_sha256,
            "original_path": self.original_path,
            "decision": self.decision,
            "decided_at": self.decided_at,
        }


@dataclass(frozen=True)
class ReviewReport:
    schema_version: int
    review_id: str
    project_root: str
    base_revision: str
    created_at: str
    updated_at: str
    status: ReviewStatus
    files: tuple[ReviewFile, ...]

    @property
    def pending_count(self) -> int:
        return sum(item.decision == "pending" for item in self.files)

    @property
    def accepted_count(self) -> int:
        return sum(item.decision == "accepted" for item in self.files)

    @property
    def reverted_count(self) -> int:
        return sum(item.decision == "reverted" for item in self.files)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "project_root": self.project_root,
            "base_revision": self.base_revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "files": [item.to_dict() for item in self.files],
            "pending_count": self.pending_count,
            "accepted_count": self.accepted_count,
            "reverted_count": self.reverted_count,
        }


class ReviewRuntime:
    """Capture readable Git diffs and apply explicit accept or safe revert decisions."""

    def capture(self, project_root: str | Path) -> ReviewReport:
        root = Path(project_root).expanduser().resolve()
        if not (root / ".git").exists():
            raise RuntimeError("Review Workspace requires a Git repository")
        base_revision = _run_git(root, "rev-parse", "HEAD").stdout.strip()
        status = _run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        entries = tuple(
            item
            for item in self._parse_status(status)
            if _reviewable_path(item[1])
            and (item[2] is None or _reviewable_path(item[2]))
        )
        files = tuple(
            self._capture_file(root, code, path, original_path)
            for code, path, original_path in entries
        )
        timestamp = _now()
        return ReviewReport(
            schema_version=1,
            review_id=uuid.uuid4().hex,
            project_root=str(root),
            base_revision=base_revision,
            created_at=timestamp,
            updated_at=timestamp,
            status="complete" if not files else "pending",
            files=files,
        )

    def accept(self, report: ReviewReport, relative_path: str) -> ReviewReport:
        root = Path(report.project_root).resolve()
        current = self._find_file(report, relative_path)
        self._assert_base_revision(root, report)
        self._assert_unchanged(root, current)
        updated_file = replace(current, decision="accepted", decided_at=_now())
        return self._replace_file(report, updated_file)

    def revert(self, report: ReviewReport, relative_path: str) -> ReviewReport:
        root = Path(report.project_root).resolve()
        current = self._find_file(report, relative_path)
        self._assert_base_revision(root, report)
        self._assert_unchanged(root, current)
        target = _safe_path(root, relative_path)
        if current.git_status == "??":
            self._remove_untracked_path(target)
        elif current.original_path is not None:
            _run_git(
                root,
                "restore",
                "--source=HEAD",
                "--staged",
                "--worktree",
                "--",
                current.original_path,
                current.relative_path,
            )
        else:
            _run_git(
                root,
                "restore",
                "--source=HEAD",
                "--staged",
                "--worktree",
                "--",
                current.relative_path,
            )
        updated_file = replace(current, decision="reverted", decided_at=_now())
        return self._replace_file(report, updated_file)

    @staticmethod
    def _remove_untracked_path(target: Path) -> None:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    @staticmethod
    def _parse_status(value: str) -> tuple[tuple[str, str, str | None], ...]:
        raw = value.split("\0")
        entries: list[tuple[str, str, str | None]] = []
        index = 0
        while index < len(raw):
            entry = raw[index]
            if not entry:
                index += 1
                continue
            if len(entry) < 4:
                raise RuntimeError("invalid git status entry")
            code = entry[:2]
            path = entry[3:]
            original_path: str | None = None
            if "R" in code or "C" in code:
                index += 1
                if index >= len(raw) or not raw[index]:
                    raise RuntimeError("renamed path is missing its source")
                original_path = raw[index]
            entries.append((code, path, original_path))
            index += 1
        entries.sort(key=lambda item: item[1])
        return tuple(entries)

    def _capture_file(
        self,
        root: Path,
        code: str,
        relative_path: str,
        original_path: str | None,
    ) -> ReviewFile:
        target = _safe_path(root, relative_path)
        if code == "??":
            diff_text, is_binary = _readable_untracked_diff(target, relative_path)
        else:
            diff_text = _run_git(
                root,
                "diff",
                "--no-ext-diff",
                "--find-renames",
                "--binary",
                "HEAD",
                "--",
                *(
                    (original_path, relative_path)
                    if original_path is not None
                    else (relative_path,)
                ),
            ).stdout
            is_binary = "GIT binary patch" in diff_text or "Binary files" in diff_text
            if not diff_text:
                diff_text = f"No textual diff available for {relative_path}.\n"
        return ReviewFile(
            relative_path=relative_path,
            git_status=code,
            change_kind=_change_kind(code),
            diff_text=diff_text,
            is_binary=is_binary,
            current_sha256=_file_sha256(target),
            original_path=original_path,
        )

    @staticmethod
    def _find_file(report: ReviewReport, relative_path: str) -> ReviewFile:
        for item in report.files:
            if item.relative_path == relative_path:
                if item.decision != "pending":
                    raise RuntimeError(f"change already decided: {relative_path}")
                return item
        raise KeyError(relative_path)

    @staticmethod
    def _assert_base_revision(root: Path, report: ReviewReport) -> None:
        current_revision = _run_git(root, "rev-parse", "HEAD").stdout.strip()
        if current_revision != report.base_revision:
            raise RuntimeError(
                "Repository HEAD changed after the review was captured. Refresh Review Workspace."
            )

    @staticmethod
    def _assert_unchanged(root: Path, item: ReviewFile) -> None:
        current_sha256 = _file_sha256(_safe_path(root, item.relative_path))
        if current_sha256 != item.current_sha256:
            raise RuntimeError(
                "Workspace changed after the diff was captured. Refresh Review Workspace before deciding."
            )
        if item.original_path is not None:
            original = _safe_path(root, item.original_path)
            if original.exists():
                raise RuntimeError(
                    "A renamed file source reappeared after the diff was captured. "
                    "Refresh Review Workspace before deciding."
                )

    @staticmethod
    def _replace_file(report: ReviewReport, updated_file: ReviewFile) -> ReviewReport:
        files = tuple(
            updated_file if item.relative_path == updated_file.relative_path else item
            for item in report.files
        )
        status: ReviewStatus = "complete" if all(item.decision != "pending" for item in files) else "pending"
        return replace(report, files=files, status=status, updated_at=_now())


class ReviewWorkspaceAdapter:
    """Persist Review Workspace reports and explicit user decisions."""

    def __init__(self, workspace_root: str | Path, runtime: ReviewRuntime | None = None) -> None:
        self.root = Path(workspace_root).expanduser().resolve() / "reviews"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime or ReviewRuntime()

    def create(self, project_root: str | Path) -> ReviewReport:
        report = self.runtime.capture(project_root)
        self.save(report)
        return report

    def save(self, report: ReviewReport) -> Path:
        destination = self.root / f"{report.review_id}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def load(self, review_id: str) -> ReviewReport:
        value = json.loads((self.root / f"{review_id}.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("review report must be an object")
        raw_files = value.get("files", [])
        if not isinstance(raw_files, list):
            raise TypeError("review files must be a list")
        files: list[ReviewFile] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                raise TypeError("review file must be an object")
            files.append(
                ReviewFile(
                    relative_path=str(raw["relative_path"]),
                    git_status=str(raw["git_status"]),
                    change_kind=self._as_change_kind(raw["change_kind"]),
                    diff_text=str(raw["diff_text"]),
                    is_binary=bool(raw["is_binary"]),
                    current_sha256=(
                        str(raw["current_sha256"])
                        if raw.get("current_sha256") is not None
                        else None
                    ),
                    original_path=(
                        str(raw["original_path"])
                        if raw.get("original_path") is not None
                        else None
                    ),
                    decision=self._as_decision(raw.get("decision", "pending")),
                    decided_at=str(raw["decided_at"]) if raw.get("decided_at") is not None else None,
                )
            )
        return ReviewReport(
            schema_version=self._as_int(value["schema_version"], "schema_version"),
            review_id=str(value["review_id"]),
            project_root=str(value["project_root"]),
            base_revision=str(value["base_revision"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            status=self._as_status(value["status"]),
            files=tuple(files),
        )

    def list_reports(self, project_root: str | None = None) -> tuple[ReviewReport, ...]:
        reports = [self.load(path.stem) for path in self.root.glob("*.json")]
        if project_root is not None:
            reports = [item for item in reports if item.project_root == project_root]
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(reports)

    def accept(self, review_id: str, relative_path: str) -> ReviewReport:
        report = self.runtime.accept(self.load(review_id), relative_path)
        self.save(report)
        return report

    def revert(self, review_id: str, relative_path: str) -> ReviewReport:
        report = self.runtime.revert(self.load(review_id), relative_path)
        self.save(report)
        return report

    @staticmethod
    def _as_int(value: object, field: str) -> int:
        if isinstance(value, bool):
            raise TypeError(f"{field} must be an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise TypeError(f"{field} must be an integer") from exc
        raise TypeError(f"{field} must be an integer")

    @staticmethod
    def _as_decision(value: object) -> ReviewDecision:
        if value == "pending":
            return "pending"
        if value == "accepted":
            return "accepted"
        if value == "reverted":
            return "reverted"
        raise ValueError("invalid review decision")

    @staticmethod
    def _as_status(value: object) -> ReviewStatus:
        if value == "pending":
            return "pending"
        if value == "complete":
            return "complete"
        raise ValueError("invalid review status")

    @staticmethod
    def _as_change_kind(value: object) -> ChangeKind:
        if value == "added":
            return "added"
        if value == "modified":
            return "modified"
        if value == "deleted":
            return "deleted"
        if value == "renamed":
            return "renamed"
        if value == "unmerged":
            return "unmerged"
        if value == "unknown":
            return "unknown"
        raise ValueError("invalid change kind")
