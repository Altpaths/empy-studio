from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .done import evaluate_done

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "releases",
    "project_vaults",
}
EXCLUDED_NAMES = {".DS_Store", ".env"}


def _version_from_pyproject(root: Path) -> str:
    for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("Version not found in pyproject.toml")


def _include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.name.startswith(".env."):
        return False
    return path.is_file()


def _git_value(root: Path, args: list[str]) -> str | None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_release(
    project_root: str | Path = ".",
    *,
    output_dir: str | Path = "releases",
    version: str | None = None,
    skip_done_check: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    release_version = version or _version_from_pyproject(root)
    destination = (root / output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    if skip_done_check:
        done_report: dict[str, Any] = {
            "engine": "definition_of_done",
            "status": "skipped",
            "checks": [],
            "failed": [],
        }
    else:
        done_report = evaluate_done(root)
        if done_report["status"] != "pass":
            return {
                "engine": "release_builder",
                "status": "blocked",
                "reason": "definition_of_done_failed",
                "done": done_report,
            }

    artifact_name = f"empy-studio-{release_version}.zip"
    artifact = destination / artifact_name

    with tempfile.TemporaryDirectory() as temp_dir:
        stage = Path(temp_dir) / f"empy-studio-{release_version}"
        stage.mkdir(parents=True)
        for path in sorted(root.rglob("*")):
            if _include(path, root):
                target = stage / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)

        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))

    sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        "project": "Empy Studio",
        "version": release_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact": artifact.name,
        "sha256": sha256,
        "size_bytes": artifact.stat().st_size,
        "git_commit": _git_value(root, ["rev-parse", "HEAD"]),
        "git_branch": _git_value(root, ["branch", "--show-current"]),
        "definition_of_done": done_report["status"],
    }

    manifest_path = destination / f"empy-studio-{release_version}.manifest.json"
    checksum_path = destination / f"empy-studio-{release_version}.sha256"
    notes_path = destination / f"empy-studio-{release_version}.release-notes.md"

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum_path.write_text(f"{sha256}  {artifact.name}\n", encoding="utf-8")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8") if (root / "CHANGELOG.md").exists() else ""
    notes_path.write_text(
        "\n".join([
            f"# Empy Studio {release_version}",
            "",
            "## Artifact",
            "",
            f"- File: `{artifact.name}`",
            f"- SHA-256: `{sha256}`",
            f"- Size: {artifact.stat().st_size} bytes",
            "",
            "## Validation",
            "",
            f"- Definition of Done: **{done_report['status'].upper()}**",
            "",
            "## Changelog",
            "",
            changelog.strip() or "No changelog available.",
            "",
        ]),
        encoding="utf-8",
    )

    return {
        "engine": "release_builder",
        "status": "built",
        "artifact": str(artifact),
        "manifest": str(manifest_path),
        "checksum": str(checksum_path),
        "release_notes": str(notes_path),
        "sha256": sha256,
        "version": release_version,
    }
