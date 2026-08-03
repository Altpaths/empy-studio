from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import load_json, save_json

_DEFAULT_EXCLUDED_NAMES = {
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
    "artifacts",
    "build",
    "dist",
    "node_modules",
    "project_vaults",
    "releases",
    "venv",
}

_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")


@dataclass(frozen=True)
class VaultPaths:
    root: Path
    baseline: Path
    knowledge: Path
    tickets: Path
    design: Path
    releases: Path
    artifacts: Path


def _paths(vault_root: Path) -> VaultPaths:
    return VaultPaths(
        root=vault_root,
        baseline=vault_root / "baseline",
        knowledge=vault_root / "knowledge",
        tickets=vault_root / "tickets",
        design=vault_root / "design",
        releases=vault_root / "releases",
        artifacts=vault_root / "artifacts",
    )


def _validate_project_id(project_id: str) -> None:
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(
            "project_id must be 2-63 characters using lowercase letters, numbers, dot, underscore, or hyphen"
        )


def _is_excluded(path: Path, project_root: Path, vault_root: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        path.relative_to(vault_root)
        return True
    except ValueError:
        pass
    relative = path.relative_to(project_root)
    return any(part in _DEFAULT_EXCLUDED_NAMES or part.startswith(".env.") for part in relative.parts)


def _iter_source_files(project_root: Path, vault_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or _is_excluded(path, project_root, vault_root):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(project_root).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_file_manifest(project_root: Path, vault_root: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in _iter_source_files(project_root, vault_root):
        manifest.append({
            "path": path.relative_to(project_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return manifest


def _write_snapshot(project_root: Path, vault_root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in _iter_source_files(project_root, vault_root):
                archive.write(path, path.relative_to(project_root).as_posix())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_vault(
    *,
    project_root: str | Path,
    vault_root: str | Path,
    project_id: str,
    project_name: str,
    snapshot: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    _validate_project_id(project_id)
    source = Path(project_root).expanduser().resolve()
    vault = Path(vault_root).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"project root does not exist or is not a directory: {source}")
    if (vault / "vault.json").exists() and not force:
        raise FileExistsError("vault already exists; use force=True to replace the baseline")

    paths = _paths(vault)
    for directory in (
        paths.baseline,
        paths.knowledge,
        paths.tickets,
        paths.design,
        paths.releases,
        paths.artifacts,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    files = _build_file_manifest(source, vault)
    baseline: dict[str, Any] = {
        "schema_version": 1,
        "project_id": project_id,
        "created_at": created_at,
        "source_root": str(source),
        "file_count": len(files),
        "total_bytes": sum(int(item["size"]) for item in files),
        "files": files,
    }
    save_json(paths.baseline / "manifest.json", baseline)

    snapshot_path = paths.baseline / "source.zip"
    if snapshot:
        _write_snapshot(source, vault, snapshot_path)

    vault_manifest: dict[str, Any] = {
        "schema_version": 1,
        "project_id": project_id,
        "project_name": project_name,
        "created_at": created_at,
        "updated_at": created_at,
        "project_root": str(source),
        "baseline_manifest": "baseline/manifest.json",
        "source_snapshot": "baseline/source.zip" if snapshot else None,
        "status": "active",
    }
    save_json(paths.root / "vault.json", vault_manifest)
    save_json(paths.tickets / "active.json", {"schema_version": 1, "tickets": []})
    save_json(paths.releases / "index.json", {"schema_version": 1, "releases": []})

    (paths.knowledge / "PROJECT_IDENTITY.md").write_text(
        f"# Project Identity\n\n"
        f"- **Name:** {project_name}\n"
        f"- **ID:** `{project_id}`\n"
        f"- **Source root:** `{source}`\n"
        f"- **Baseline created:** {created_at}\n"
        f"- **Baseline files:** {len(files)}\n",
        encoding="utf-8",
    )
    (paths.knowledge / "DECISIONS.md").write_text(
        "# Decisions\n\nRecord locked product, architecture, design, and release decisions here.\n",
        encoding="utf-8",
    )

    return vault_status(paths.root)


def vault_status(vault_root: str | Path) -> dict[str, Any]:
    vault = Path(vault_root).expanduser().resolve()
    vault_file = vault / "vault.json"
    baseline_file = vault / "baseline" / "manifest.json"
    if not vault_file.exists() or not baseline_file.exists():
        raise FileNotFoundError("not a valid Empy Studio Project Vault")

    metadata = load_json(vault_file)
    baseline = load_json(baseline_file)
    snapshot_value = metadata.get("source_snapshot")
    snapshot_path = vault / str(snapshot_value) if snapshot_value else None
    checks = {
        "vault_manifest": vault_file.exists(),
        "baseline_manifest": baseline_file.exists(),
        "source_snapshot": snapshot_path.exists() if snapshot_path else None,
        "project_identity": (vault / "knowledge" / "PROJECT_IDENTITY.md").exists(),
        "decision_log": (vault / "knowledge" / "DECISIONS.md").exists(),
    }
    return {
        "engine": "empy_studio.vault",
        "project_id": metadata["project_id"],
        "project_name": metadata["project_name"],
        "vault_root": str(vault),
        "file_count": baseline["file_count"],
        "total_bytes": baseline["total_bytes"],
        "snapshot_sha256": _sha256(snapshot_path) if snapshot_path and snapshot_path.exists() else None,
        "checks": checks,
        "status": "ready" if all(value is not False for value in checks.values()) else "incomplete",
    }
