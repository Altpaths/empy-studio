from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_release_assets import (
    _artifact_records,
    _write_checksums,
)
from scripts.verify_release_assets import verify_release_assets


def _write_fixture(root: Path) -> Path:
    package = root / "empy_studio-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("empy_studio/__init__.py", b"")
    installer = root / "install-macos-arm64.sh"
    installer.write_text("#!/bin/sh\nTARGET=macos-arm64\n", encoding="utf-8")
    app_archive = root / "empy-studio-macos-arm64.zip"
    with zipfile.ZipFile(app_archive, "w") as archive:
        archive.writestr("Empy Studio.app/Contents/MacOS/Empy Studio", b"binary")
        archive.writestr(
            "Empy Studio.app/Contents/Resources/empy_studio/web/empy-logo.png",
            b"logo",
        )
    distribution = root / "distribution-manifest.json"
    distribution.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Empy Studio",
                "version": "0.1.0",
                "release_tag": "v0.1.0",
                "repository": "Altpaths/empy-studio",
                "minimum_python": "3.10",
                "assets": [
                    {
                        "target": "macos-arm64",
                        "asset_name": installer.name,
                        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
                        "size_bytes": installer.stat().st_size,
                        "media_type": "text/x-shellscript",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    notes = root / "RELEASE_NOTES.md"
    notes.write_text(
        "# Empy Studio v0.1.0\n\nRelease candidate notes.\n",
        encoding="utf-8",
    )
    records = _artifact_records(root)
    _write_checksums(root, records)
    manifest = {
        "schema_version": 1,
        "product": "Empy Studio",
        "version": "0.1.0",
        "release_tag": "v0.1.0",
        "repository": "Altpaths/empy-studio",
        "artifacts": _artifact_records(root),
        "checksums": "SHA256SUMS",
    }
    path = root / "release-assets.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_release_asset_verification_round_trip(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)

    result = verify_release_assets(manifest)

    assert result["status"] == "verified"
    assert result["installer_count"] == 1

    with pytest.raises(ValueError, match="Notarization evidence"):
        verify_release_assets(manifest, require_notarized=True)


def test_release_asset_verification_rejects_tampering(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    package = tmp_path / "empy_studio-0.1.0-py3-none-any.whl"
    package.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_release_assets(manifest)


@pytest.mark.parametrize(
    "member",
    (
        ".empy/CHANGE_REQUEST.md",
        ".env.production",
        "credentials.json",
        "private/signing.key",
    ),
)
def test_release_asset_verification_rejects_contaminated_wheels(
    tmp_path: Path,
    member: str,
) -> None:
    manifest = _write_fixture(tmp_path)
    package = tmp_path / "empy_studio-0.1.0-py3-none-any.whl"
    package.unlink()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(member, b"do not ship")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for item in data["artifacts"]:
        if item["path"] == package.name:
            item["sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
            item["size_bytes"] = package.stat().st_size
    _write_checksums(
        tmp_path,
        [item for item in data["artifacts"] if item["path"] != "SHA256SUMS"],
    )
    for item in data["artifacts"]:
        if item["path"] == "SHA256SUMS":
            checksum = tmp_path / "SHA256SUMS"
            item["sha256"] = hashlib.sha256(checksum.read_bytes()).hexdigest()
            item["size_bytes"] = checksum.stat().st_size
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="(forbidden|sensitive|key material)"):
        verify_release_assets(manifest)


def test_release_asset_verification_rejects_contaminated_macos_app(
    tmp_path: Path,
) -> None:
    manifest = _write_fixture(tmp_path)
    app_archive = tmp_path / "empy-studio-macos-arm64.zip"
    app_archive.unlink()
    with zipfile.ZipFile(app_archive, "w") as archive:
        archive.writestr("Empy Studio.app/Contents/MacOS/Empy Studio", b"binary")
        archive.writestr(
            "Empy Studio.app/Contents/Resources/empy_studio/web/empy-logo.png",
            b"logo",
        )
        archive.writestr("Empy Studio.app/Contents/Resources/.env.production", b"secret")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for item in data["artifacts"]:
        if item["path"] == app_archive.name:
            item["sha256"] = hashlib.sha256(app_archive.read_bytes()).hexdigest()
            item["size_bytes"] = app_archive.stat().st_size
    _write_checksums(
        tmp_path,
        [item for item in data["artifacts"] if item["path"] != "SHA256SUMS"],
    )
    for item in data["artifacts"]:
        if item["path"] == "SHA256SUMS":
            checksum = tmp_path / "SHA256SUMS"
            item["sha256"] = hashlib.sha256(checksum.read_bytes()).hexdigest()
            item["size_bytes"] = checksum.stat().st_size
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="sensitive"):
        verify_release_assets(manifest)
