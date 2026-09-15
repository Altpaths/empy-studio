from __future__ import annotations

import hashlib
import json
import os
import re
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
        ".cache",
        "coverage",
        "dist",
        "node_modules",
        ".next",
        ".nuxt",
        ".parcel-cache",
        ".svelte-kit",
        ".tox",
        ".turbo",
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
    ".map",
    ".min.css",
    ".min.js",
    ".zip",
)

MAX_EXPORT_MANIFEST_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def is_verification_manifest(relative: PurePosixPath | str) -> bool:
    """Return whether a path is the one safe project verification contract.

    Empy owns the rest of ``.empy``.  The user supplied verification contract
    is the sole exception because dropping it during import makes a project
    appear to have no tests and can cause a provider run to spend tokens before
    the real verification failure is visible.
    """

    path = PurePosixPath(str(relative).replace("\\", "/"))
    return len(path.parts) >= 2 and path.parts[-2:] == (".empy", "verification.json")


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
    *,
    allow_verification_manifest: bool = False,
) -> bool:
    if is_sensitive_relative_path(relative):
        return True
    # Keep the project supplied verification contract available to the local
    # verification pipeline while excluding every other Empy runtime file.
    # Ancestors such as ``vendor/.empy/verification.json`` remain excluded.
    allowed_manifest = allow_verification_manifest and is_verification_manifest(relative)
    parts = relative.parts[:-2] if allowed_manifest else relative.parts
    return any(
        part in excluded_names
        or part.startswith(".env.")
        or part.lower().endswith(EXCLUDED_SUFFIXES)
        for part in parts
    )


def _safe_member_name(
    name: str,
    excluded_names: frozenset[str] = IMPORT_EXCLUDED_NAMES,
    *,
    allow_verification_manifest: bool = False,
) -> PurePosixPath | None:
    normalized = name.replace("\\", "/")
    if (
        "\x00" in normalized
        or normalized.startswith("/")
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        return None
    if not normalized:
        return None
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or _excluded(
            relative,
            excluded_names,
            allow_verification_manifest=allow_verification_manifest,
        )
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
        elif ".empy" in parts or is_sensitive_relative_path(PurePosixPath(normalized)):
            category = "sensitive_or_runtime"
        elif _safe_member_name(raw_name, allow_verification_manifest=True) is None:
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
    return _safe_member_name(name, allow_verification_manifest=True)


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
    allow_verification_manifest: bool = False,
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
            manifest_directory = (
                allow_verification_manifest
                and directory == ".empy"
                and not _excluded(current_relative, excluded_names)
            )
            if (
                _excluded(
                    relative,
                    excluded_names,
                    allow_verification_manifest=allow_verification_manifest,
                )
                or candidate.is_symlink()
            ) and not manifest_directory:
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
            if (
                _excluded(
                    relative,
                    excluded_names,
                    allow_verification_manifest=allow_verification_manifest,
                )
                or candidate.is_symlink()
            ):
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
        allow_verification_manifest=not for_delivery,
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
    try:
        members, skipped_members = _walk_files(
            source_path,
            allow_verification_manifest=True,
        )
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
        usable_members = tuple(
            item
            for item in _safe_files(destination)
            if not is_verification_manifest(item[1])
        )
        if not usable_members:
            raise ValueError("project import contains no safe files")
        _initialize_git(destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
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
    seen_members: set[str] = set()
    try:
        archive_handle = zipfile.ZipFile(source_path)
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError("project archive is not a readable ZIP file") from exc
    try:
        with archive_handle as archive:
            for info in archive.infolist():
                relative = _safe_member_name(
                    info.filename,
                    allow_verification_manifest=True,
                )
                if relative is None or _is_zip_symlink(info):
                    skipped.append(info.filename)
                    continue
                archive_name = info.filename.rstrip("/") if info.is_dir() else info.filename
                if relative.as_posix() != archive_name:
                    skipped.append(info.filename)
                    continue
                if info.is_dir():
                    continue
                relative_name = relative.as_posix()
                if relative_name in seen_members:
                    raise ValueError(
                        f"project archive contains duplicate file path: {relative_name}"
                    )
                seen_members.add(relative_name)
                if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                    raise ValueError(f"archive member is too large: {info.filename}")
                total_bytes += info.file_size
                if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("project archive exceeds the total size limit")
                target = destination / Path(relative_name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source_stream, target.open("wb") as target_stream:
                    shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
                extracted.append(relative)
    except Exception:
        # Extraction is transactional from the caller's perspective.  A
        # malformed or oversized upload must not leave a partially imported
        # tree that could be selected by a later session.
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if not extracted or not any(not is_verification_manifest(item) for item in extracted):
        raise ValueError("project archive contains no safe files")
    top_levels = {item.parts[0] for item in extracted}
    project_root = destination / next(iter(top_levels)) if len(top_levels) == 1 else destination
    try:
        _initialize_git(project_root)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return ImportedProject(
        source_path,
        project_root,
        destination,
        tuple(skipped),
        len(extracted),
    )


def _deterministic_zip(
    destination: Path,
    members: Iterable[tuple[Path, str]],
    *,
    contents: dict[str, bytes] | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative in members:
            # Archive names are project-relative so uploading the ZIP into a
            # DirectAdmin domain/project root and extracting it places
            # public_html/... and sibling paths directly where they belong.
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(
                info,
                contents[relative] if contents is not None else source.read_bytes(),
            )


def _expected_manifest(
    root: Path,
    members: tuple[tuple[Path, str], ...],
    *,
    contents: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_name": root.name,
        "file_count": len(members),
        "files": [
            {
                "path": relative,
                "size": len(contents[relative]) if contents is not None else source.stat().st_size,
                "sha256": (
                    _sha256_bytes(contents[relative])
                    if contents is not None
                    else _sha256_file(source)
                ),
            }
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
                relative = _safe_member_name(
                    info.filename,
                    allow_verification_manifest=True,
                )
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
                relative = _safe_member_name(
                    info.filename,
                    allow_verification_manifest=True,
                )
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


def _manifest_error(message: str) -> ValueError:
    return ValueError(f"export manifest is invalid: {message}")


def validate_export_manifest(manifest: object) -> dict[str, Any]:
    """Validate the versioned manifest emitted with a deployment archive.

    The manifest is an integrity contract, not display metadata.  Keeping the
    accepted shape small prevents a corrupted or hand-edited sidecar from
    being treated as proof that an archive is safe to deploy.
    """

    if not isinstance(manifest, dict):
        raise _manifest_error("the root must be an object")
    allowed_fields = {
        "schema_version",
        "project_name",
        "file_count",
        "files",
        "archive_mode",
        "extraction_root",
        "deployment_instruction",
        "baseline_snapshot_sha256",
        "changed_files",
        "deleted_files",
    }
    unknown_fields = sorted(
        (key for key in manifest if key not in allowed_fields),
        key=str,
    )
    if unknown_fields:
        raise _manifest_error(
            "contains unsupported field(s): " + ", ".join(str(item) for item in unknown_fields)
        )
    schema_version = manifest.get("schema_version")
    if schema_version != 3:
        raise _manifest_error("schema_version must be 3")
    if manifest.get("archive_mode") != "delta":
        raise _manifest_error("archive_mode must be delta")
    if manifest.get("extraction_root") != ".":
        raise _manifest_error("extraction_root must be .")
    project_name = manifest.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip() or len(project_name) > 255:
        raise _manifest_error("project_name must be a non-empty short string")
    file_count = manifest.get("file_count")
    files = manifest.get("files")
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 1:
        raise _manifest_error("file_count must be a positive integer")
    if not isinstance(files, list) or len(files) != file_count:
        raise _manifest_error("files must contain exactly file_count entries")
    normalized_files: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_file in enumerate(files):
        if not isinstance(raw_file, dict):
            raise _manifest_error(f"files[{index}] must be an object")
        path = raw_file.get("path")
        size = raw_file.get("size")
        sha256 = raw_file.get("sha256")
        if not isinstance(path, str):
            raise _manifest_error(f"files[{index}].path must be a string")
        safe_path = _safe_member_name(path, DELIVERY_EXCLUDED_NAMES)
        if safe_path is None or not safe_path.parts or safe_path.as_posix() != path:
            raise _manifest_error(f"files[{index}].path is unsafe")
        unknown_file_fields = sorted(
            (key for key in raw_file if key not in {"path", "size", "sha256"}),
            key=str,
        )
        if unknown_file_fields:
            raise _manifest_error(
                f"files[{index}] contains unsupported field(s): "
                + ", ".join(str(item) for item in unknown_file_fields)
            )
        if path in seen:
            raise _manifest_error(f"files contains duplicate path {path}")
        seen.add(path)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise _manifest_error(f"files[{index}].size must be a non-negative integer")
        if size > MAX_ARCHIVE_FILE_BYTES:
            raise _manifest_error(f"files[{index}] exceeds the file size limit")
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            raise _manifest_error(f"files[{index}].sha256 is not a SHA-256 digest")
        normalized_files.append({"path": path, "size": size, "sha256": sha256})

    changed_files = manifest.get("changed_files")
    deleted_files = manifest.get("deleted_files")
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        raise _manifest_error("changed_files must be a string list")
    if tuple(changed_files) != tuple(item["path"] for item in normalized_files):
        raise _manifest_error("changed_files does not match files")
    if not isinstance(deleted_files, list) or not all(isinstance(item, str) for item in deleted_files):
        raise _manifest_error("deleted_files must be a string list")
    deleted_seen: set[str] = set()
    for item in deleted_files:
        safe_path = _safe_member_name(item, DELIVERY_EXCLUDED_NAMES)
        if safe_path is None or safe_path.as_posix() != item:
            raise _manifest_error("deleted_files contains an unsafe path")
        if item in deleted_seen or item in seen:
            raise _manifest_error("deleted_files contains a duplicate or shipped path")
        deleted_seen.add(item)
    baseline_sha256 = manifest.get("baseline_snapshot_sha256")
    if not isinstance(baseline_sha256, str) or _SHA256_RE.fullmatch(baseline_sha256) is None:
        raise _manifest_error("baseline_snapshot_sha256 is not a SHA-256 digest")
    deployment_instruction = manifest.get("deployment_instruction")
    if not isinstance(deployment_instruction, str) or not deployment_instruction.strip():
        raise _manifest_error("deployment_instruction must be present")
    if len(deployment_instruction) > 4096:
        raise _manifest_error("deployment_instruction is too long")
    # Return a normalized copy so callers never rely on arbitrary values from
    # a JSON decoder or on mutable lists held by an untrusted sidecar.
    return {
        "schema_version": 3,
        "project_name": project_name,
        "file_count": file_count,
        "files": normalized_files,
        "archive_mode": "delta",
        "extraction_root": ".",
        "deployment_instruction": deployment_instruction,
        "baseline_snapshot_sha256": baseline_sha256,
        "changed_files": list(changed_files),
        "deleted_files": list(deleted_files),
    }


def _validate_legacy_export_manifest(manifest: object) -> dict[str, Any]:
    """Normalize the pre-v3 manifest accepted by the public archive verifier.

    v1 sidecars did not carry extraction or baseline metadata, so they cannot
    be trusted for restore/download.  ``verify_project_archive`` still
    accepts them for callers that used the original API, while all current
    delivery paths require the stricter v3 contract above.
    """

    if not isinstance(manifest, dict):
        raise _manifest_error("the legacy root must be an object")
    schema_version = manifest.get("schema_version", 1)
    if isinstance(schema_version, bool) or schema_version != 1:
        raise _manifest_error(
            f"schema_version {schema_version!r} is unsupported; use v3 for delivery artifacts"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise _manifest_error(
            "legacy files must be a non-empty list; export the project again for a v3 manifest"
        )
    normalized_files: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_file in enumerate(files):
        if not isinstance(raw_file, dict):
            raise _manifest_error(f"legacy files[{index}] must be an object")
        path = raw_file.get("path")
        size = raw_file.get("size")
        sha256 = raw_file.get("sha256")
        safe_path = (
            _safe_member_name(path, DELIVERY_EXCLUDED_NAMES)
            if isinstance(path, str)
            else None
        )
        if safe_path is None or not safe_path.parts or safe_path.as_posix() != path:
            raise _manifest_error(f"legacy files[{index}].path is unsafe")
        if path in seen:
            raise _manifest_error(f"legacy files contains duplicate path {path}")
        seen.add(path)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise _manifest_error(f"legacy files[{index}].size must be non-negative")
        if size > MAX_ARCHIVE_FILE_BYTES:
            raise _manifest_error(f"legacy files[{index}] exceeds the file size limit")
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            raise _manifest_error(f"legacy files[{index}].sha256 is not a SHA-256 digest")
        normalized_files.append({"path": path, "size": size, "sha256": sha256})
    file_count = manifest.get("file_count", len(normalized_files))
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count != len(normalized_files)
    ):
        raise _manifest_error("legacy file_count does not match files")
    return {
        "schema_version": 1,
        "file_count": file_count,
        "files": normalized_files,
    }


def _read_export_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("export manifest is missing; export the project again")
    try:
        if path.stat().st_size > MAX_EXPORT_MANIFEST_BYTES:
            raise _manifest_error("file exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise _manifest_error("file is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise _manifest_error(f"invalid JSON ({exc.msg})") from exc
    return validate_export_manifest(value)


def _assert_workspace_file(path: Path, workspace_root: Path | None, label: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = candidate.resolve()
    if workspace_root is not None:
        workspace = workspace_root.expanduser().resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"{label} is outside the Empy workspace") from exc
    return resolved


def validate_export_artifacts(
    archive_path: str | Path,
    manifest_path: str | Path,
    checksum_path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_file_count: int | None = None,
    expected_changed_files: Iterable[str] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate an exported ZIP and both sidecars before restore/download.

    The returned normalized manifest is safe for state restoration.  Every
    caller gets the same archive, checksum, path, and manifest checks, so a
    deleted or tampered release cannot be resurrected as ``verified=True``.
    """

    workspace = Path(workspace_root).expanduser().resolve() if workspace_root is not None else None
    archive = _assert_workspace_file(Path(archive_path), workspace, "export archive")
    manifest_file = _assert_workspace_file(Path(manifest_path), workspace, "export manifest")
    checksum_file = _assert_workspace_file(Path(checksum_path), workspace, "export checksum")
    if archive.suffix.casefold() != ".zip" or not archive.is_file() or archive.is_symlink():
        raise FileNotFoundError("export archive is missing; export the project again")
    manifest = _read_export_manifest(manifest_file)
    if not checksum_file.is_file() or checksum_file.is_symlink():
        raise FileNotFoundError("export checksum is missing; export the project again")
    try:
        checksum_text = checksum_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("export checksum is unreadable; export the project again") from exc
    actual_sha256 = _sha256_file(archive)
    expected_checksum = f"{actual_sha256}  {archive.name}"
    if checksum_text != expected_checksum:
        raise ValueError("export checksum does not match the archive; export it again")
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError("export archive changed since it was recorded; export it again")
    if expected_file_count is not None and manifest["file_count"] != expected_file_count:
        raise ValueError("export manifest file count does not match the recorded release")
    if expected_changed_files is not None and tuple(manifest["changed_files"]) != tuple(expected_changed_files):
        raise ValueError("export manifest changed files do not match the recorded release")
    verify_project_archive(archive, manifest)
    return manifest


def review_snapshot_drift(
    project_root: str | Path,
    review_files: Iterable[object],
) -> tuple[str, ...]:
    """Return accepted Review files whose bytes changed before export."""

    root = Path(project_root).expanduser().resolve()

    def resolve_member(relative: str) -> Path | None:
        candidate = root / Path(relative)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        # A symlinked parent can otherwise make a safe lexical path point
        # outside the isolated project while the final component is regular.
        current = candidate
        while current != root:
            if current.is_symlink():
                return None
            current = current.parent
        return candidate

    drift: list[str] = []
    for item in review_files:
        decision = getattr(item, "decision", None)
        if decision != "accepted":
            continue
        relative = str(getattr(item, "relative_path", ""))
        safe = _safe_member_name(relative, DELIVERY_EXCLUDED_NAMES)
        if safe is None or safe.as_posix() != relative:
            drift.append(f"{relative or '<unknown file>'}: review path is unsafe")
            continue
        target = resolve_member(relative)
        if target is None or target.is_symlink():
            drift.append(f"{relative}: file became a symlink after Review")
            continue
        try:
            actual = _sha256_file(target) if target.is_file() else None
        except OSError:
            actual = None
        expected = getattr(item, "current_sha256", None)
        if actual != expected:
            drift.append(f"{relative}: file changed after Review; refresh Review before export")
        original = getattr(item, "original_path", None)
        if original:
            original_relative = str(original)
            original_target = resolve_member(original_relative)
            if original_target is None:
                drift.append(f"{relative}: renamed source path is unsafe")
            elif original_target.exists() or original_target.is_symlink():
                drift.append(f"{relative}: renamed source reappeared after Review")
    return tuple(drift)


def _stable_member_contents(members: tuple[tuple[Path, str], ...]) -> dict[str, bytes]:
    """Read export members once and reject a concurrent source mutation."""

    contents: dict[str, bytes] = {}
    for source, relative in members:
        try:
            before = _sha256_file(source)
            data = source.read_bytes()
            after = _sha256_file(source)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Could not read {relative} safely for export: {exc}") from exc
        data_hash = _sha256_bytes(data)
        if before != data_hash or after != data_hash:
            raise RuntimeError(
                f"Project file {relative} changed while export was being prepared; export again."
            )
        contents[relative] = data
    return contents


def verify_project_archive(archive_path: str | Path, manifest: dict[str, Any]) -> None:
    archive_candidate = Path(archive_path).expanduser()
    if archive_candidate.is_symlink():
        raise ValueError("export archive must not be a symlink")
    archive = archive_candidate.resolve()
    if not isinstance(manifest, dict):
        raise _manifest_error("the root must be an object")
    schema_version = manifest.get("schema_version", 1)
    if schema_version == 3:
        normalized_manifest = validate_export_manifest(manifest)
    elif schema_version == 1:
        normalized_manifest = _validate_legacy_export_manifest(manifest)
    else:
        raise _manifest_error(
            f"schema_version {schema_version!r} is unsupported; use v3 for delivery artifacts"
        )
    expected_files = {
        str(item["path"]): str(item["sha256"])
        for item in normalized_manifest["files"]
    }
    expected_sizes = {
        str(item["path"]): int(item["size"])
        for item in normalized_manifest["files"]
    }
    if not archive.is_file() or archive.is_symlink():
        raise FileNotFoundError("export archive is missing; export the project again")
    try:
        with zipfile.ZipFile(archive) as handle:
            bad_member = handle.testzip()
            if bad_member is not None:
                raise ValueError("exported archive is corrupt")
            archive_infos = handle.infolist()
            names: dict[str, zipfile.ZipInfo] = {}
            total_bytes = 0
            for info in archive_infos:
                relative = _safe_member_name(info.filename, DELIVERY_EXCLUDED_NAMES)
                if relative is None:
                    raise ValueError("exported archive contains an unsafe or protected path")
                archive_name = info.filename.rstrip("/") if info.is_dir() else info.filename
                if relative.as_posix() != archive_name:
                    raise ValueError("exported archive contains a non-canonical path")
                normalized_name = relative.as_posix()
                if normalized_name in names:
                    raise ValueError("exported archive contains duplicate paths")
                names[normalized_name] = info
                if info.is_dir():
                    continue
                if _is_zip_symlink(info):
                    raise ValueError("exported archive contains a symlink")
                if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                    raise ValueError("exported archive contains an oversized file")
                total_bytes += info.file_size
                if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("exported archive exceeds the total size limit")
                if info.file_size != expected_sizes.get(normalized_name):
                    raise ValueError("exported archive file size does not match its manifest")
            actual: dict[str, str] = {}
            for name, info in names.items():
                if info.is_dir():
                    continue
                actual[name] = _sha256_bytes(handle.read(info))
    except zipfile.BadZipFile as exc:
        raise ValueError("exported archive is not a readable ZIP file") from exc
    if actual != expected_files:
        raise ValueError("exported archive failed its manifest verification")


def export_project_zip(
    project_root: str | Path,
    destination: str | Path,
    *,
    baseline_snapshot: str | Path | None = None,
    review_files: Iterable[object] | None = None,
) -> ExportedProject:
    """Create a verified ZIP containing only files changed since import.

    A baseline snapshot is mandatory by design. Falling back to a full-project
    archive would make a deployment ZIP misleading and could overwrite files
    that Empy never changed.
    """

    if baseline_snapshot is None:
        raise ValueError("A baseline snapshot is required for a change-only ZIP.")
    root = Path(project_root).expanduser().resolve()
    if review_files is not None:
        drift = review_snapshot_drift(root, review_files)
        if drift:
            shown = "; ".join(drift[:10])
            extra = f"; and {len(drift) - 10} more" if len(drift) > 10 else ""
            raise RuntimeError(
                "Review snapshot drift detected; refresh Review before creating the ZIP: "
                f"{shown}{extra}"
            )
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
    contents = _stable_member_contents(members)
    target = Path(destination).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target / f"{root.name}-release.zip"
    if target.exists():
        raise FileExistsError(target)
    manifest = _expected_manifest(root, members, contents=contents)
    manifest.update(
        {
            "schema_version": 3,
            "archive_mode": "delta",
            "extraction_root": ".",
            "deployment_instruction": (
                "Extract this ZIP in the server folder corresponding to the imported project root. "
                "If ZIP paths start with public_html/, use its parent domain/project folder, "
                "not public_html itself. If the imported root was public_html, extract there. "
                "Only listed changed files are replaced; review the manifest and back up those files first."
            ),
            "baseline_snapshot_sha256": delta.baseline_sha256,
            "changed_files": list(delta.changed_files),
            "deleted_files": list(delta.deleted_files),
        }
    )
    manifest_path = target.with_suffix(".manifest.json")
    checksum_path = target.with_suffix(target.suffix + ".sha256")
    temporary_archive = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary_manifest: Path | None = None
    temporary_checksum: Path | None = None
    try:
        _deterministic_zip(temporary_archive, members, contents=contents)
        verify_project_archive(temporary_archive, manifest)
        temporary_archive.replace(target)
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_manifest.write_text(manifest_text, encoding="utf-8")
        temporary_manifest.replace(manifest_path)
        checksum = _sha256_file(target)
        temporary_checksum = checksum_path.with_name(f".{checksum_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_checksum.write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
        temporary_checksum.replace(checksum_path)
        validate_export_artifacts(
            target,
            manifest_path,
            checksum_path,
            expected_sha256=checksum,
            expected_file_count=len(members),
            expected_changed_files=delta.changed_files,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
        if temporary_checksum is not None:
            temporary_checksum.unlink(missing_ok=True)
        temporary_archive.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
        if temporary_checksum is not None:
            temporary_checksum.unlink(missing_ok=True)
        temporary_archive.unlink(missing_ok=True)
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
