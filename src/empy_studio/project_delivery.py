from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .core.path_policy import is_sensitive_relative_path
from .release_validation import validate_changed_html_links

MAX_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_FILE_BYTES = MAX_ARCHIVE_FILE_BYTES
MAX_UPLOAD_TOTAL_BYTES = MAX_ARCHIVE_TOTAL_BYTES

IMPORT_EXCLUDED_NAMES = frozenset(
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
        "outputs",
        "private",
        "releases",
        "venv",
        "work",
    }
)
# Dependencies are part of the isolated execution workspace when the source
# already contains them. They are excluded only from the final delivery ZIP;
# otherwise importing a valid Composer or Node project silently makes its own
# verification impossible.
DELIVERY_EXCLUDED_NAMES = IMPORT_EXCLUDED_NAMES | frozenset(
    {
        "build",
        "coverage",
        "dist",
        "node_modules",
        "vendor",
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
    copied_members: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "project_root": str(self.project_root),
            "workspace_root": str(self.workspace_root),
            "skipped_members": list(self.skipped_members),
            "copied_members": self.copied_members,
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
    archive_mode: str = "delta"
    changed_files: tuple[str, ...] = ()
    deleted_files: tuple[str, ...] = ()
    baseline_sha256: str | None = None
    extraction_root: str | None = None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        for key in ("project_root", "archive_path", "manifest_path", "checksum_path"):
            value[key] = str(value[key])
        return value


@dataclass(frozen=True)
class ProjectDelta:
    """Safe, project-relative difference from the imported baseline snapshot."""

    changed_members: tuple[tuple[Path, str], ...]
    deleted_files: tuple[str, ...]
    baseline_sha256: str

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(relative for _source, relative in self.changed_members)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded(
    relative: PurePosixPath,
    excluded_names: frozenset[str] = IMPORT_EXCLUDED_NAMES,
) -> bool:
    if is_sensitive_relative_path(relative):
        return True
    return any(
        part in excluded_names
        or part.startswith(".env.")
        or part.lower().endswith(EXCLUDED_SUFFIXES)
        for part in relative.parts
    )


def _safe_member_name(
    name: str,
    excluded_names: frozenset[str] = IMPORT_EXCLUDED_NAMES,
) -> PurePosixPath | None:
    normalized = name.replace("\\", "/").strip("/")
    if not normalized:
        return None
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or _excluded(relative, excluded_names)
    ):
        return None
    return relative


def summarize_import_skips(skipped_members: Iterable[str]) -> dict[str, int]:
    """Classify excluded import entries without exposing their paths."""

    counts: Counter[str] = Counter()
    for raw_name in skipped_members:
        normalized = raw_name.replace("\\", "/").strip("/")
        parts = PurePosixPath(normalized).parts
        if raw_name.startswith("<") or not normalized:
            category = "access_or_copy"
        elif "__MACOSX" in parts:
            category = "macos_metadata"
        elif ".git" in parts:
            category = "git_metadata"
        elif any(part in {"node_modules", "vendor", "venv", ".venv"} for part in parts):
            category = "dependencies"
        elif is_sensitive_relative_path(PurePosixPath(normalized)):
            category = "sensitive_or_runtime"
        elif _safe_member_name(raw_name) is None:
            category = "unsafe_path"
        else:
            category = "access_or_copy"
        counts[category] += 1
    return dict(sorted(counts.items()))


def safe_upload_relative_path(name: str) -> PurePosixPath | None:
    """Validate a browser-uploaded project-relative path."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        return None
    return _safe_member_name(name)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


_BROAD_IMPORT_ROOTS = frozenset(
    {
        "/",
        "/Applications",
        "/Library",
        "/System",
        "/System/Volumes/Data",
        "/Users",
        "/Volumes",
        "/private",
        "/usr",
        "/var",
        "/home",
    }
)


def _validate_import_source(root: Path) -> None:
    normalized = root.as_posix().rstrip("/") or "/"
    anchor = Path(root.anchor) if root.anchor else None
    if normalized in _BROAD_IMPORT_ROOTS or (anchor is not None and root == anchor):
        raise PermissionError(
            "Choose a project folder, not a system or user root directory."
        )
    if "/apptranslocation/" in f"/{normalized.casefold()}/":
        raise PermissionError(
            "Choose the original project location instead of a translocated app path."
        )
    try:
        root.stat()
        if not os.access(root, os.R_OK | os.X_OK):
            raise PermissionError(root)
    except OSError as exc:
        if isinstance(exc, PermissionError):
            raise
        raise OSError(exc.errno, "The selected project path cannot be inspected.") from exc


def _walk_files(
    root: Path,
    *,
    excluded_names: frozenset[str] = IMPORT_EXCLUDED_NAMES,
) -> tuple[tuple[tuple[Path, str], ...], tuple[str, ...]]:
    """Walk a project without aborting on one unreadable or excluded path."""
    members: list[tuple[Path, str]] = []
    skipped: list[str] = []

    def onerror(error: OSError) -> None:
        filename = getattr(error, "filename", None)
        skipped.append(str(filename or "<unreadable directory>"))

    for current, directories, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=onerror,
    ):
        current_path = Path(current)
        current_relative = PurePosixPath(
            current_path.relative_to(root).as_posix()
        ) if current_path != root else PurePosixPath()
        kept_directories: list[str] = []
        for directory in sorted(directories):
            relative = current_relative / directory
            candidate = current_path / directory
            if _excluded(relative, excluded_names) or candidate.is_symlink():
                skipped.append(relative.as_posix())
                if (
                    is_sensitive_relative_path(relative)
                    and candidate.is_dir()
                    and not candidate.is_symlink()
                ):
                    for nested_current, _nested_directories, nested_files in os.walk(
                        candidate,
                        topdown=True,
                        followlinks=False,
                        onerror=onerror,
                    ):
                        nested_path = Path(nested_current)
                        for nested_file in sorted(nested_files):
                            skipped.append(
                                PurePosixPath(
                                    nested_path.joinpath(nested_file)
                                    .relative_to(root)
                                    .as_posix()
                                ).as_posix()
                            )
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories
        for filename in sorted(filenames):
            relative = current_relative / filename
            candidate = current_path / filename
            if _excluded(relative, excluded_names) or candidate.is_symlink():
                skipped.append(relative.as_posix())
                continue
            try:
                if candidate.is_file():
                    members.append((candidate, relative.as_posix()))
                else:
                    skipped.append(relative.as_posix())
            except OSError:
                skipped.append(relative.as_posix())
    return tuple(members), tuple(skipped)


def _safe_files(
    root: Path,
    *,
    for_delivery: bool = False,
) -> tuple[tuple[Path, str], ...]:
    """Return safe files for import or final delivery, depending on the mode."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    members, _skipped = _walk_files(
        root,
        excluded_names=(
            DELIVERY_EXCLUDED_NAMES if for_delivery else IMPORT_EXCLUDED_NAMES
        ),
    )
    return members


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


def checkpoint_accepted_changes(
    project_root: str | Path,
    relative_paths: Iterable[str],
) -> None:
    """Checkpoint accepted changes inside Empy's isolated workspace only."""

    root = Path(project_root).expanduser().resolve()
    paths = tuple(
        dict.fromkeys(
            str(item).replace("\\", "/").strip("/")
            for item in relative_paths
        )
    )
    if not paths:
        return
    if not (root / ".git").is_dir():
        raise RuntimeError("Accepted-change checkpoint requires an Empy Git workspace")
    for relative in paths:
        path = PurePosixPath(relative)
        if not relative or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"invalid accepted checkpoint path: {relative!r}")
        if is_sensitive_relative_path(path):
            raise ValueError(f"sensitive path cannot be checkpointed: {relative}")
    _run_git(root, "add", "--all", "--", *paths)
    _run_git(
        root,
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "Empy accepted checkpoint",
    )


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
    _validate_import_source(source_path)
    destination = _new_workspace(Path(workspace_root), source_path.name)
    members, skipped_members = _walk_files(source_path)
    skipped = list(skipped_members)
    copied_members = 0
    for path, relative_name in members:
        target = destination / Path(relative_name)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied_members += 1
        except OSError:
            skipped.append(relative_name)
    if not _safe_files(destination):
        raise ValueError("project import contains no safe files")
    _initialize_git(destination)
    return ImportedProject(
        source_path,
        destination,
        destination,
        tuple(skipped),
        copied_members,
    )


def import_project_archive(source: str | Path, workspace_root: str | Path) -> ImportedProject:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file() or source_path.suffix.lower() != ".zip":
        raise ValueError("project archive must be a ZIP file")
    _validate_import_source(source_path.parent)
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
    return ImportedProject(
        source_path,
        project_root,
        destination,
        tuple(skipped),
        len(extracted),
    )


def _deterministic_zip(destination: Path, members: Iterable[tuple[Path, str]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative in members:
            # Archive names are project-relative so uploading the ZIP into a
            # DirectAdmin domain/project root and extracting it places
            # public_html/... and sibling paths directly where they belong.
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
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


def _baseline_hashes(snapshot: str | Path) -> tuple[dict[str, str], str]:
    """Read and validate the immutable source snapshot used for delta export."""

    snapshot_path = Path(snapshot).expanduser().resolve()
    if not snapshot_path.is_file() or snapshot_path.suffix.casefold() != ".zip":
        raise FileNotFoundError("Empy baseline snapshot is missing; re-import the project.")
    hashes: dict[str, str] = {}
    total_bytes = 0
    try:
        with zipfile.ZipFile(snapshot_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError("Empy baseline snapshot is corrupt; re-import the project.")
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = _safe_member_name(info.filename)
                if relative is None or _is_zip_symlink(info):
                    raise ValueError("Empy baseline snapshot contains an unsafe path.")
                if relative.as_posix() in hashes:
                    raise ValueError("Empy baseline snapshot contains duplicate files.")
                if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                    raise ValueError("Empy baseline snapshot contains an oversized file.")
                total_bytes += info.file_size
                if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("Empy baseline snapshot exceeds the safe size limit.")
                if _excluded(relative, DELIVERY_EXCLUDED_NAMES):
                    continue
                with archive.open(info) as stream:
                    hashes[relative.as_posix()] = _sha256_bytes(stream.read())
    except zipfile.BadZipFile as exc:
        raise ValueError("Empy baseline snapshot is corrupt; re-import the project.") from exc
    return hashes, _sha256_file(snapshot_path)


def inspect_project_delta(
    project_root: str | Path,
    baseline_snapshot: str | Path,
) -> ProjectDelta:
    """Compare the current isolated project with its immutable import snapshot."""

    root = Path(project_root).expanduser().resolve()
    current_members = _safe_files(root, for_delivery=True)
    current_hashes = {
        relative: _sha256_file(source) for source, relative in current_members
    }
    baseline_hashes, baseline_sha256 = _baseline_hashes(baseline_snapshot)
    changed_members = tuple(
        (source, relative)
        for source, relative in current_members
        if baseline_hashes.get(relative) != current_hashes[relative]
    )
    deleted_files = tuple(sorted(set(baseline_hashes) - set(current_hashes)))
    return ProjectDelta(
        changed_members=changed_members,
        deleted_files=deleted_files,
        baseline_sha256=baseline_sha256,
    )


def materialize_baseline_copy(
    baseline_snapshot: str | Path,
    destination: str | Path,
) -> int:
    """Create a safe full test copy from the immutable baseline snapshot.

    The destination must not already contain files. This deliberately creates a
    separate copy so verification or recovery inspection cannot mutate the
    working project.
    """

    snapshot_path = Path(baseline_snapshot).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise FileExistsError(target)
    if target.is_dir():
        target.rmdir()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    extracted = 0
    total_bytes = 0
    try:
        with zipfile.ZipFile(snapshot_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError("Empy baseline snapshot is corrupt; re-import the project.")
            seen: set[str] = set()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = _safe_member_name(info.filename)
                if relative is None or _is_zip_symlink(info):
                    raise ValueError("Empy baseline snapshot contains an unsafe path.")
                relative_name = relative.as_posix()
                if relative_name in seen:
                    raise ValueError("Empy baseline snapshot contains duplicate files.")
                seen.add(relative_name)
                if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                    raise ValueError("Empy baseline snapshot contains an oversized file.")
                total_bytes += info.file_size
                if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("Empy baseline snapshot exceeds the safe size limit.")
                output = temporary / Path(relative_name)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output.open("wb") as destination_stream:
                    shutil.copyfileobj(source, destination_stream, length=1024 * 1024)
                extracted += 1
        if not extracted:
            raise ValueError("Empy baseline snapshot contains no safe files.")
        temporary.replace(target)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return extracted


def verify_project_archive(archive_path: str | Path, manifest: dict[str, Any]) -> None:
    archive = Path(archive_path).expanduser().resolve()
    expected_files = {str(item["path"]): str(item["sha256"]) for item in manifest["files"]}
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
        if any(name.startswith("/") or ".." in PurePosixPath(name).parts for name in names):
            raise ValueError("exported archive contains an unsafe path")
        actual: dict[str, str] = {}
        for name in names:
            if name.endswith("/"):
                continue
            if _safe_member_name(name, DELIVERY_EXCLUDED_NAMES) is None:
                raise ValueError("exported archive contains a protected path")
            actual[name] = _sha256_bytes(handle.read(name))
    if actual != expected_files:
        raise ValueError("exported archive failed its manifest verification")


def export_project_zip(
    project_root: str | Path,
    destination: str | Path,
    *,
    baseline_snapshot: str | Path | None = None,
) -> ExportedProject:
    """Create a verified ZIP containing only files changed since import.

    A baseline snapshot is mandatory by design. Falling back to a full-project
    archive would make a deployment ZIP misleading and could overwrite files
    that Empy never changed.
    """

    if baseline_snapshot is None:
        raise ValueError("A baseline snapshot is required for a change-only ZIP.")
    root = Path(project_root).expanduser().resolve()
    delta = inspect_project_delta(root, baseline_snapshot)
    if delta.deleted_files:
        raise ValueError(
            "The project has deleted file(s); a ZIP extraction cannot delete them "
            "automatically. Restore the file or use an explicit deletion step."
        )
    members = delta.changed_members
    if not members:
        raise ValueError("No changed project files are available for a delta ZIP.")
    validate_changed_html_links(root, members)
    target = Path(destination).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target / f"{root.name}-release.zip"
    if target.exists():
        raise FileExistsError(target)
    manifest = _expected_manifest(root, members)
    manifest.update(
        {
            "schema_version": 3,
            "archive_mode": "delta",
            "extraction_root": ".",
            "deployment_instruction": (
                "Upload this ZIP into the project/domain root in DirectAdmin and extract it there."
            ),
            "baseline_snapshot_sha256": delta.baseline_sha256,
            "changed_files": list(delta.changed_files),
            "deleted_files": list(delta.deleted_files),
        }
    )
    _deterministic_zip(target, members)
    verify_project_archive(target, manifest)
    manifest_path = target.with_suffix(".manifest.json")
    checksum_path = target.with_suffix(target.suffix + ".sha256")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum = _sha256_file(target)
    checksum_path.write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    return ExportedProject(
        project_root=root,
        archive_path=target,
        manifest_path=manifest_path,
        checksum_path=checksum_path,
        sha256=checksum,
        file_count=len(members),
        verified=True,
        archive_mode="delta",
        changed_files=delta.changed_files,
        deleted_files=delta.deleted_files,
        baseline_sha256=delta.baseline_sha256,
        extraction_root=".",
    )
