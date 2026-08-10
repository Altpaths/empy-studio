#!/usr/bin/env python3
"""Verify a release-assets.json tree before publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_FORBIDDEN_ARCHIVE_PARTS = {
    ".empy",
    ".venv",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "outputs",
    "work",
    "private",
    "releases",
    "artifacts",
    "__pycache__",
}
_FORBIDDEN_ARCHIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "service-account.json",
    "id_rsa",
}
_FORBIDDEN_ARCHIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError(f"Artifact path must be relative: {raw!r}")
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Artifact path escapes release root: {raw!r}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _verify_archive_members(
    names: Sequence[str],
    *,
    label: str,
    reject_nested_zip: bool,
) -> None:
    for raw_name in names:
        normalized = raw_name.replace("\\", "/").strip("/")
        parts = Path(normalized).parts
        if any(part in _FORBIDDEN_ARCHIVE_PARTS for part in parts):
            raise ValueError(f"{label} contains forbidden path: {raw_name}")
        basename = parts[-1] if parts else ""
        if basename in _FORBIDDEN_ARCHIVE_NAMES or basename.startswith(".env."):
            raise ValueError(f"{label} contains sensitive file: {raw_name}")
        if basename.lower().endswith(_FORBIDDEN_ARCHIVE_SUFFIXES):
            raise ValueError(f"{label} contains sensitive key material: {raw_name}")
        if reject_nested_zip and basename.lower().endswith(".zip"):
            raise ValueError(f"{label} contains nested ZIP: {raw_name}")


def _verify_macos_app_archive(
    path: Path,
    *,
    require_notarized: bool,
    evidence: dict[str, dict[str, Any]],
) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Corrupt macOS app archive member: {bad_member}")
            names = tuple(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid macOS app archive: {path.name}") from exc
    _verify_archive_members(names, label="macOS app archive", reject_nested_zip=False)
    required_suffixes = (
        "Empy Studio.app/Contents/MacOS/Empy Studio",
        "Empy Studio.app/Contents/Resources/empy_studio/web/empy-logo.png",
    )
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in names):
            raise ValueError(f"macOS app archive is missing: {suffix}")
    if require_notarized:
        architecture = path.stem.removeprefix("empy-studio-macos-")
        record = evidence.get(architecture)
        if record is None:
            raise ValueError(
                f"Notarization evidence is missing for macOS {architecture}"
            )
        if (
            record.get("status") != "notarized"
            or record.get("notarization") != "accepted"
            or record.get("stapled") is not True
            or record.get("gatekeeper") != "accepted"
        ):
            raise ValueError(
                f"macOS {architecture} release evidence is not final"
            )


def _verify_source_archive(path: Path) -> None:
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if any(part in _FORBIDDEN_ARCHIVE_PARTS for part in parts):
                    raise ValueError(
                        f"Source archive contains forbidden path: {member.name}"
                    )
                if member.name.endswith(".zip"):
                    raise ValueError(f"Source archive contains nested ZIP: {member.name}")
    except tarfile.TarError as exc:
        raise ValueError(f"Invalid source distribution: {path.name}") from exc


def _verify_wheel_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Corrupt wheel archive member: {bad_member}")
            _verify_archive_members(
                archive.namelist(),
                label="wheel archive",
                reject_nested_zip=True,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid wheel distribution: {path.name}") from exc


def _load_notarization_evidence(
    root: Path,
    artifacts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        relative = item["path"]
        if not relative.startswith("macos-signing-evidence-") or not relative.endswith(
            ".json"
        ):
            continue
        path = _relative_file(root, relative)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"macOS release evidence must be an object: {relative}")
        architecture = value.get("architecture")
        if not isinstance(architecture, str) or architecture in evidence:
            raise ValueError(f"Invalid or duplicate macOS release evidence: {relative}")
        evidence[architecture] = value
    return evidence


def verify_release_assets(
    manifest_path: Path,
    *,
    require_notarized: bool = False,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    root = manifest_path.parent
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported release asset manifest")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Release asset manifest has no artifacts")
    evidence = _load_notarization_evidence(root, artifacts)
    paths: set[str] = set()
    verified: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise TypeError("Artifact record must be an object")
        relative = item.get("path")
        if not isinstance(relative, str) or relative in paths:
            raise ValueError(f"Duplicate or invalid artifact path: {relative!r}")
        paths.add(relative)
        path = _relative_file(root, relative)
        expected_sha = item.get("sha256")
        expected_size = item.get("size_bytes")
        actual_sha = sha256_file(path)
        actual_size = path.stat().st_size
        if actual_sha != expected_sha:
            raise ValueError(f"SHA-256 mismatch: {relative}")
        if actual_size != expected_size:
            raise ValueError(f"Size mismatch: {relative}")
        if path.name.startswith("empy-studio-macos-") and path.suffix == ".zip":
            _verify_macos_app_archive(
                path,
                require_notarized=require_notarized,
                evidence=evidence,
            )
        if path.suffix == ".whl":
            _verify_wheel_archive(path)
        if path.name.endswith(".tar.gz"):
            _verify_source_archive(path)
        verified.append({"path": relative, "sha256": actual_sha, "size_bytes": actual_size})

    checksum_name = data.get("checksums")
    if not isinstance(checksum_name, str):
        raise TypeError("Manifest must name a checksum file")
    checksum_path = _relative_file(root, checksum_name)
    checksum_lines = checksum_path.read_text(encoding="utf-8").splitlines()
    expected_lines = {
        f"{item['sha256']}  {item['path']}"
        for item in artifacts
        if item["path"] != checksum_name
    }
    if set(checksum_lines) != expected_lines:
        raise ValueError("SHA256SUMS does not match release artifacts")

    distribution_manifests = [
        item["path"] for item in artifacts if item["path"].endswith("distribution-manifest.json")
    ]
    if len(distribution_manifests) != 1:
        raise ValueError("Exactly one distribution manifest is required")
    distribution_path = _relative_file(root, distribution_manifests[0])
    distribution = json.loads(distribution_path.read_text(encoding="utf-8"))
    assets = distribution.get("assets") if isinstance(distribution, dict) else None
    if not isinstance(assets, list) or not assets:
        raise ValueError("Distribution manifest has no installer assets")
    distribution_root = distribution_path.parent
    for asset in assets:
        if not isinstance(asset, dict):
            raise TypeError("Distribution asset record must be an object")
        asset_path = distribution_root / str(asset["asset_name"])
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)
        if sha256_file(asset_path) != asset["sha256"]:
            raise ValueError(f"Distribution asset SHA-256 mismatch: {asset_path.name}")
        if asset_path.stat().st_size != asset["size_bytes"]:
            raise ValueError(f"Distribution asset size mismatch: {asset_path.name}")

    release_notes = [item["path"] for item in artifacts if item["path"] == "RELEASE_NOTES.md"]
    if len(release_notes) != 1:
        raise ValueError("Exactly one RELEASE_NOTES.md asset is required")
    notes = _relative_file(root, release_notes[0]).read_text(encoding="utf-8").strip()
    if not notes or "Empy Studio" not in notes or str(data.get("release_tag")) not in notes:
        raise ValueError("RELEASE_NOTES.md is empty or does not identify this release")
    app_architectures = {
        Path(item["path"]).stem.removeprefix("empy-studio-macos-")
        for item in artifacts
        if Path(item["path"]).name.startswith("empy-studio-macos-")
        and Path(item["path"]).suffix == ".zip"
    }
    if require_notarized and app_architectures != set(evidence):
        raise ValueError("Notarization evidence must exist for every macOS app archive")

    return {
        "status": "verified",
        "release_tag": data.get("release_tag"),
        "artifact_count": len(verified),
        "installer_count": len(assets),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--require-notarized",
        action="store_true",
        help="Require accepted notarization, stapling, and Gatekeeper evidence",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            verify_release_assets(
                args.manifest,
                require_notarized=args.require_notarized,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
