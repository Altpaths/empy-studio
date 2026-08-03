from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from empy_studio.plugin_package import (
    build_package,
    inspect_package,
)


def create_plugin(root: Path) -> Path:
    plugin = root / "example-plugin"
    payload = plugin / "payload"
    payload.mkdir(parents=True)

    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "example-plugin",
                "name": "Example Plugin",
                "version": "1.0.0",
                "empy_requires": ">=0.1.0",
                "entrypoint": "example_plugin:Plugin",
                "hooks": ["agent"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (payload / "example_plugin.py").write_text(
        "class Plugin:\n    pass\n",
        encoding="utf-8",
    )
    return plugin


def test_build_and_inspect_verified_package(
    tmp_path: Path,
) -> None:
    source = create_plugin(tmp_path)
    package = build_package(
        source,
        tmp_path / "example-plugin.empy-plugin",
        signature_metadata={
            "algorithm": "ed25519",
            "key_id": "test-key",
            "signature": "placeholder",
        },
    )

    inspection = inspect_package(
        package,
        empy_version="1.0.0",
    )

    assert inspection.manifest.plugin_id == "example-plugin"
    assert inspection.signed
    assert inspection.records


def test_tampered_payload_is_rejected(tmp_path: Path) -> None:
    source = create_plugin(tmp_path)
    package = build_package(
        source,
        tmp_path / "example-plugin.empy-plugin",
    )
    tampered = tmp_path / "tampered.empy-plugin"

    with zipfile.ZipFile(package, "r") as archive:
        members = {
            name: archive.read(name)
            for name in archive.namelist()
        }

    members["payload/example_plugin.py"] = b"tampered = True\n"

    with zipfile.ZipFile(tampered, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)

    with pytest.raises(
        ValueError,
        match="mismatch",
    ):
        inspect_package(
            tampered,
            empy_version="1.0.0",
        )


def test_unrecorded_payload_is_rejected(
    tmp_path: Path,
) -> None:
    source = create_plugin(tmp_path)
    package = build_package(
        source,
        tmp_path / "example-plugin.empy-plugin",
    )
    invalid = tmp_path / "invalid.empy-plugin"

    with zipfile.ZipFile(package, "r") as archive:
        members = {
            name: archive.read(name)
            for name in archive.namelist()
        }

    members["payload/extra.py"] = b"extra = True\n"

    with zipfile.ZipFile(invalid, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)

    with pytest.raises(
        ValueError,
        match="integrity records",
    ):
        inspect_package(
            invalid,
            empy_version="1.0.0",
        )


def test_path_traversal_is_rejected(
    tmp_path: Path,
) -> None:
    package = tmp_path / "unsafe.empy-plugin"

    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../escape.py", "bad")
        archive.writestr("plugin.json", "{}")
        archive.writestr(
            "RECORD.sha256.json",
            '{"files": []}',
        )

    with pytest.raises(
        ValueError,
        match="Unsafe package path",
    ):
        inspect_package(
            package,
            empy_version="1.0.0",
        )
