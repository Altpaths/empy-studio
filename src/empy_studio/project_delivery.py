from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .core.path_policy import is_sensitive_relative_path

MAX_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024

EXCLUDED_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".empy",
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
        "outputs",
        "private",
        "releases",
        "vendor",
        "venv",
        "work",
    }
)
EXCLUDED_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".zip",
)


@dataclass(frozen=True)
class ImportedProject:
    source: Path
    project_root: Path
    workspace_root: Path
    skipped_members: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "project_root": str(self.project_root),
            "workspace_root": str(self.workspace_root),
            "skipped_members": list(self.skipped_members),
        }


@dataclass(frozen=True)
class ExportedProject:
    project_root: Path
    archive_path: Path
    manifest_path: Path
    checksum_path: Path
    sha256: str
    file_count: int
    verified: bool

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        for key in ("project_root", "archive_path", "manifest_path", "checksum_path"):
            value[key] = str(value[key])
        return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded(relative: PurePosixPath) -> bool:
    if is_sensitive_relative_path(relative):
        return True
    return any(
        part in EXCLUDED_NAMES
        or part.startswith(".env.")
        or part.lower().endswith(EXCLUDED_SUFFIXES)
        for part in relative.parts
    )


def _safe_member_name(name: str) -> PurePosixPath | None:
    normalized = name.replace("\\", "/").strip("/")
    if not normalized:
        return None
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts or _excluded(relative):
        return None
    return relative


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def _safe_files(root: Path) -> tuple[tuple[Path, str], ...]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    members: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if _excluded(relative):
            continue
        members.append((path, relative.as_posix()))
    return tuple(members)


def _run_git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(detail)


def _initialize_git(root: Path) -> None:
    _run_git(root, "init", "--quiet")
    _run_git(root, "config", "user.name", "Empy Studio")
    _run_git(root, "config", "user.email", "empy-studio@localhost")
    _run_git(root, "add", "--all")
    _run_git(root, "commit", "--quiet", "--allow-empty", "-m", "Empy baseline")


def _new_workspace(workspace_root: Path, source_name: str) -> Path:
    workspace_root = workspace_root.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    slug = "".join(character if character.isalnum() or character in "-_." else "-" for character in source_name)
    slug = slug.strip(".-") or "project"
    target = workspace_root / f"{slug}-{uuid.uuid4().hex[:10]}"
    target.mkdir()
    return target


def import_project_folder(source: str | Path, workspace_root: str | Path) -> ImportedProject:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_dir():
        raise NotADirectoryError(source_path)
    destination = _new_workspace(Path(workspace_root), source_path.name)
    skipped: list[str] = []
    for path in sorted(source_path.rglob("*")):
        relative = PurePosixPath(path.relative_to(source_path).as_posix())
        if _excluded(relative) or path.is_symlink():
            skipped.append(relative.as_posix())
            continue
        if not path.is_file():
            continue
        target = destination / Path(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if not _safe_files(destination):
        raise ValueError("project import contains no safe files")
    _initialize_git(destination)
    return ImportedProject(source_path, destination, destination, tuple(skipped))


def import_project_archive(source: str | Path, workspace_root: str | Path) -> ImportedProject:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file() or source_path.suffix.lower() != ".zip":
        raise ValueError("project archive must be a ZIP file")
    destination = _new_workspace(Path(workspace_root), source_path.stem)
    skipped: list[str] = []
    total_bytes = 0
    extracted: list[PurePosixPath] = []
    with zipfile.ZipFile(source_path) as archive:
        for info in archive.infolist():
            relative = _safe_member_name(info.filename)
            if relative is None or _is_zip_symlink(info):
                skipped.append(info.filename)
                continue
            if info.is_dir():
                continue
            if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                raise ValueError(f"archive member is too large: {info.filename}")
            total_bytes += info.file_size
            if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                raise ValueError("project archive exceeds the total size limit")
            target = destination / Path(relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source_stream, target.open("wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
            extracted.append(relative)
    if not extracted:
        raise ValueError("project archive contains no safe files")
    top_levels = {item.parts[0] for item in extracted}
    project_root = destination / next(iter(top_levels)) if len(top_levels) == 1 else destination
    _initialize_git(project_root)
    return ImportedProject(source_path, project_root, destination, tuple(skipped))


def _deterministic_zip(destination: Path, root_name: str, members: Iterable[tuple[Path, str]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative in members:
            info = zipfile.ZipInfo(f"{root_name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def _expected_manifest(root: Path, members: tuple[tuple[Path, str], ...]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_name": root.name,
        "file_count": len(members),
        "files": [
            {"path": relative, "size": source.stat().st_size, "sha256": _sha256_file(source)}
            for source, relative in members
        ],
    }


def verify_project_archive(archive_path: str | Path, manifest: dict[str, Any]) -> None:
    archive = Path(archive_path).expanduser().resolve()
    expected_root = str(manifest["project_name"])
    expected_files = {str(item["path"]): str(item["sha256"]) for item in manifest["files"]}
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
        if any(name.startswith("/") or ".." in PurePosixPath(name).parts for name in names):
            raise ValueError("exported archive contains an unsafe path")
        if any(name.split("/", 1)[0] != expected_root for name in names):
            raise ValueError("exported archive must contain exactly one project root")
        actual: dict[str, str] = {}
        for name in names:
            if name.endswith("/"):
                continue
            relative = name.split("/", 1)[1]
            actual[relative] = _sha256_bytes(handle.read(name))
    if actual != expected_files:
        raise ValueError("exported archive failed its manifest verification")


def export_project_zip(
    project_root: str | Path,
    destination: str | Path,
) -> ExportedProject:
    root = Path(project_root).expanduser().resolve()
    members = _safe_files(root)
    if not members:
        raise ValueError("cannot export a project with no safe files")
    target = Path(destination).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target / f"{root.name}-release.zip"
    if target.exists():
        raise FileExistsError(target)
    manifest = _expected_manifest(root, members)
    _deterministic_zip(target, root.name, members)
    verify_project_archive(target, manifest)
    manifest_path = target.with_suffix(".manifest.json")
    checksum_path = target.with_suffix(target.suffix + ".sha256")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum = _sha256_file(target)
    checksum_path.write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    return ExportedProject(root, target, manifest_path, checksum_path, checksum, len(members), True)
