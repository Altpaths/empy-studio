from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .plugin_manifest import PluginManifest

PACKAGE_SUFFIX = ".empy-plugin"
MANIFEST_NAME = "plugin.json"
RECORD_NAME = "RECORD.sha256.json"
SIGNATURE_NAME = "SIGNATURE.json"
PAYLOAD_PREFIX = "payload/"


@dataclass(frozen=True)
class PackageRecord:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PackageInspection:
    package_path: str
    manifest: PluginManifest
    records: tuple[PackageRecord, ...]
    signed: bool
    signature_metadata: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_path": self.package_path,
            "manifest": self.manifest.to_dict(),
            "records": [asdict(item) for item in self.records],
            "signed": self.signed,
            "signature_metadata": self.signature_metadata,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe package path: {name}")
    if not path.parts:
        raise ValueError("Package contains an empty path")


def _read_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        raw = archive.read(name)
    except KeyError as exc:
        raise ValueError(f"Plugin package is missing {name}") from exc

    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{name} must contain a JSON object")
    return value


def inspect_package(
    package_path: str | Path,
    *,
    empy_version: str,
) -> PackageInspection:
    path = Path(package_path)
    if path.suffix != PACKAGE_SUFFIX:
        raise ValueError(f"Plugin package must use the {PACKAGE_SUFFIX} suffix")
    if not path.is_file():
        raise FileNotFoundError(path)

    with zipfile.ZipFile(path, "r") as archive:
        members = archive.namelist()
        for member in members:
            _validate_member_name(member)

        manifest = PluginManifest.from_dict(
            _read_json(archive, MANIFEST_NAME)
        )
        if not manifest.supports(empy_version):
            raise ValueError(
                f"Plugin {manifest.plugin_id} {manifest.version} is not "
                f"compatible with Empy Studio {empy_version}"
            )

        raw_records = _read_json(archive, RECORD_NAME)
        entries = raw_records.get("files")
        if not isinstance(entries, list):
            raise TypeError("RECORD.sha256.json 'files' must be a list")

        records: list[PackageRecord] = []
        recorded_paths: set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError("Package record entries must be objects")

            record = PackageRecord(
                path=str(entry["path"]),
                sha256=str(entry["sha256"]),
                size_bytes=int(entry["size_bytes"]),
            )
            _validate_member_name(record.path)

            if record.path in recorded_paths:
                raise ValueError(f"Duplicate package record: {record.path}")
            recorded_paths.add(record.path)

            try:
                data = archive.read(record.path)
            except KeyError as exc:
                raise ValueError(
                    f"Recorded package file is missing: {record.path}"
                ) from exc

            if len(data) != record.size_bytes:
                raise ValueError(
                    f"Size mismatch for package file: {record.path}"
                )
            if _sha256(data) != record.sha256:
                raise ValueError(
                    f"SHA-256 mismatch for package file: {record.path}"
                )

            records.append(record)

        actual_payload = {
            member
            for member in members
            if member.startswith(PAYLOAD_PREFIX)
            and not member.endswith("/")
        }
        recorded_payload = {
            item
            for item in recorded_paths
            if item.startswith(PAYLOAD_PREFIX)
        }
        if actual_payload != recorded_payload:
            raise ValueError(
                "Payload files and integrity records do not match"
            )

        signature_metadata = (
            _read_json(archive, SIGNATURE_NAME)
            if SIGNATURE_NAME in members
            else None
        )

        module_name, _ = manifest.entrypoint.split(":", 1)
        module_file = (
            PAYLOAD_PREFIX + module_name.replace(".", "/") + ".py"
        )
        package_init = (
            PAYLOAD_PREFIX
            + module_name.replace(".", "/")
            + "/__init__.py"
        )
        if (
            module_file not in actual_payload
            and package_init not in actual_payload
        ):
            raise ValueError(
                f"Entrypoint module is missing from payload: {module_name}"
            )

        return PackageInspection(
            package_path=str(path.resolve()),
            manifest=manifest,
            records=tuple(records),
            signed=signature_metadata is not None,
            signature_metadata=signature_metadata,
        )


def build_package(
    source_dir: str | Path,
    destination: str | Path,
    *,
    signature_metadata: dict[str, Any] | None = None,
) -> Path:
    source = Path(source_dir).resolve()
    manifest_path = source / MANIFEST_NAME
    payload_root = source / "payload"

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    if not payload_root.is_dir():
        raise FileNotFoundError(payload_root)

    manifest_data = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    if not isinstance(manifest_data, dict):
        raise TypeError("plugin.json must contain a JSON object")

    manifest = PluginManifest.from_dict(manifest_data)

    output = Path(destination)
    if output.is_dir():
        output = output / (
            f"{manifest.plugin_id}-{manifest.version}{PACKAGE_SUFFIX}"
        )
    if output.suffix != PACKAGE_SUFFIX:
        raise ValueError(
            f"Destination must use the {PACKAGE_SUFFIX} suffix"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    payload_files = sorted(
        path
        for path in payload_root.rglob("*")
        if path.is_file()
    )
    if not payload_files:
        raise ValueError("Plugin payload cannot be empty")

    with tempfile.TemporaryDirectory(
        prefix="empy-plugin-build-"
    ) as temp_dir:
        staged = Path(temp_dir)
        shutil.copy2(manifest_path, staged / MANIFEST_NAME)
        staged_payload = staged / "payload"
        shutil.copytree(payload_root, staged_payload)

        records: list[dict[str, Any]] = []
        for file_path in sorted(staged_payload.rglob("*")):
            if not file_path.is_file():
                continue

            relative = file_path.relative_to(staged).as_posix()
            data = file_path.read_bytes()
            records.append(
                {
                    "path": relative,
                    "sha256": _sha256(data),
                    "size_bytes": len(data),
                }
            )

        (staged / RECORD_NAME).write_text(
            json.dumps(
                {
                    "format": "empy-plugin-record-v1",
                    "files": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if signature_metadata is not None:
            (staged / SIGNATURE_NAME).write_text(
                json.dumps(
                    signature_metadata,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for file_path in sorted(staged.rglob("*")):
                if file_path.is_file():
                    archive.write(
                        file_path,
                        file_path.relative_to(staged).as_posix(),
                    )

    return output
