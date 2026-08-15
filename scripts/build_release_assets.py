#!/usr/bin/env python3
"""Build package and installer assets without publishing them.

The command is intentionally network-free. It builds the package locally,
generates installers whose embedded URL and digest point at that package, and
writes a manifest that can be verified before any GitHub release is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from empy_studio.distribution_builder import (
    DistributionBuildConfig,
    build_distribution,
)
from empy_studio.release_version import ReleaseVersion

_PACKAGE_VERSION_PATTERN = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)(?:(?P<kind>a|b|rc)(?P<number>\d+))?$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(command), cwd=cwd, check=True)


def _tag_version(package_version: str) -> str:
    match = _PACKAGE_VERSION_PATTERN.fullmatch(package_version)
    if match is None:
        raise ValueError(
            "Package version must use MAJOR.MINOR.PATCH with an optional "
            f"aN, bN, or rcN suffix: {package_version!r}"
        )
    core = match.group("core")
    kind = match.group("kind")
    number = match.group("number")
    if kind is None or number is None:
        return core
    return f"{core}-{kind}.{number}"


def _source_package_version(source_root: Path) -> str:
    """Read the release version from the source tree being built.

    Release generation must not depend on whichever Empy wheel happens to be
    installed in the caller's virtual environment.  That made it possible to
    build the current source with an older tag when ``PYTHONPATH`` was used.
    """

    path = source_root / "pyproject.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    project = document.get("project")
    if not isinstance(project, dict):
        raise TypeError("pyproject.toml project table is invalid")
    if not isinstance(project.get("version"), str):
        raise TypeError("pyproject.toml must define project.version")
    version = project["version"].strip()
    if not version:
        raise ValueError("project.version cannot be empty")
    return version


def _require_single(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        names = ", ".join(path.name for path in paths)
        raise RuntimeError(
            f"Expected exactly one {label}; found {len(paths)}: {names}"
        )
    return paths[0]


def _media_type(path: Path) -> str:
    if path.suffix == ".whl":
        return "application/octet-stream"
    if path.suffix == ".sh":
        return "text/x-shellscript"
    if path.suffix == ".ps1":
        return "text/plain"
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".md":
        return "text/markdown"
    return "application/octet-stream"


def _release_notes(
    source_root: Path,
    *,
    package_version: str,
    release_tag: str,
    package_filename: str,
) -> str:
    changelog_path = source_root / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise FileNotFoundError(changelog_path)
    lines = changelog_path.read_text(encoding="utf-8").splitlines()
    headings = [
        (index, line)
        for index, line in enumerate(lines)
        if line.startswith("## [")
    ]
    selected_index: int | None = None
    selected_heading = ""
    for index, line in headings:
        if line == f"## [{package_version}]" or line.startswith(
            f"## [{package_version}] - "
        ):
            selected_index = index
            selected_heading = line
            break
    if selected_index is None:
        for index, line in headings:
            if line.strip() == "## [Unreleased]":
                selected_index = index
                selected_heading = line
                break
    if selected_index is None:
        raise ValueError(
            "CHANGELOG.md must contain a matching version section or "
            "## [Unreleased] for release notes"
        )
    end_index = next(
        (index for index, _line in headings if index > selected_index),
        len(lines),
    )
    body = "\n".join(lines[selected_index + 1 : end_index]).strip()
    if not body:
        raise ValueError(f"CHANGELOG section is empty: {selected_heading}")
    return (
        f"# Empy Studio {release_tag}\n\n"
        f"{body}\n\n"
        "## Distribution\n\n"
        f"- Package: `{package_filename}`\n"
        f"- Version: `{package_version}`\n"
        f"- Release tag: `{release_tag}`\n\n"
        "## Verification\n\n"
        "Every published asset is listed in `release-assets.json` and "
        "covered by `SHA256SUMS`. Verify the manifest before installation.\n"
    )


def _artifact_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "release-assets.json":
            continue
        records.append(
            {
                "name": path.name,
                "path": relative,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "media_type": _media_type(path),
            }
        )
    if not records:
        raise RuntimeError("Release asset directory is empty")
    return records


def _write_checksums(root: Path, records: list[dict[str, Any]]) -> None:
    checksum_path = root / "SHA256SUMS"
    lines = [
        f"{record['sha256']}  {record['path']}"
        for record in records
        if record["path"] != "SHA256SUMS"
    ]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_release_assets(
    *,
    source_root: Path,
    output: Path,
    repository: str,
    release_tag: str,
    minimum_python: str,
) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing release output: {output}"
        )
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise ValueError("repository must use OWNER/REPO format")

    package_version = _source_package_version(source_root)
    if not release_tag:
        release_tag = f"v{_tag_version(package_version)}"
    if not release_tag.startswith("v") or "/" in release_tag:
        raise ValueError("release_tag must be a simple v<version> tag")
    expected_tag = f"v{_tag_version(package_version)}"
    if release_tag != expected_tag:
        raise ValueError(
            f"Release tag {release_tag!r} does not match installed package "
            f"version {package_version!r}; expected {expected_tag!r}"
        )

    release_version = ReleaseVersion.parse(release_tag[1:])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="empy-release-assets-", dir=output.parent))
    try:
        build_root = temporary / "build"
        packages = build_root / "packages"
        packages.mkdir(parents=True)
        _run(
            (
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--sdist",
                "--outdir",
                str(packages),
                str(source_root),
            ),
            # Run outside the project root.  A local ``build/`` output
            # directory would otherwise shadow the PyPA ``build`` module.
            cwd=source_root.parent,
        )
        wheel = _require_single(sorted(packages.glob("*.whl")), "wheel")
        sdist = _require_single(sorted(packages.glob("*.tar.gz")), "source distribution")

        distribution_output = build_root / "distribution"
        distribution = build_distribution(
            DistributionBuildConfig(
                product="Empy Studio",
                version=release_version,
                repository=repository,
                minimum_python=minimum_python,
                package_url=(
                    f"https://github.com/{repository}/releases/download/"
                    f"{release_tag}/{wheel.name}"
                ),
                package_sha256=sha256_file(wheel),
                package_filename=wheel.name,
                output_dir=str(distribution_output),
            )
        )

        manifest_source = Path(distribution.manifest_path)
        if not manifest_source.is_file():
            raise RuntimeError("Distribution builder did not produce a manifest")
        asset_root = temporary / "assets"
        asset_root.mkdir()
        shutil.copy2(wheel, asset_root / wheel.name)
        shutil.copy2(sdist, asset_root / sdist.name)
        distribution_root = manifest_source.parent
        for asset in sorted(distribution_root.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, asset_root / asset.name)
        shutil.copy2(manifest_source, asset_root / "distribution-manifest.json")
        config = {
            "product": "Empy Studio",
            "version": str(release_version),
            "release_tag": release_tag,
            "repository": repository,
            "minimum_python": minimum_python,
            "package_filename": wheel.name,
            "package_sha256": sha256_file(wheel),
            "distribution_manifest": "distribution-manifest.json",
        }
        (asset_root / "distribution-build.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (asset_root / "RELEASE_NOTES.md").write_text(
            _release_notes(
                source_root,
                package_version=package_version,
                release_tag=release_tag,
                package_filename=wheel.name,
            ),
            encoding="utf-8",
        )

        # Ensure the package outputs are present before hashing the release.
        if not (asset_root / wheel.name).is_file() or not (asset_root / sdist.name).is_file():
            raise RuntimeError("Release package outputs are incomplete")
        records = _artifact_records(asset_root)
        _write_checksums(asset_root, records)
        records = _artifact_records(asset_root)
        manifest = {
            "schema_version": 1,
            "product": "Empy Studio",
            "version": str(release_version),
            "release_tag": release_tag,
            "repository": repository,
            "artifacts": records,
            "checksums": "SHA256SUMS",
        }
        (asset_root / "release-assets.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        os.replace(asset_root, output)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", default="Altpaths/empy-studio")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--minimum-python", default="3.10")
    args = parser.parse_args(argv)
    manifest = build_release_assets(
        source_root=args.source_root,
        output=args.output,
        repository=args.repository,
        release_tag=args.release_tag,
        minimum_python=args.minimum_python,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
