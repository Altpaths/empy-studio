#!/usr/bin/env python3
"""Add independently built assets to a release manifest and rehash it."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from build_release_assets import _artifact_records, _write_checksums


def merge_release_assets(root: Path, extra_paths: Sequence[Path]) -> dict[str, Any]:
    root = root.expanduser().resolve()
    manifest_path = root / "release-assets.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported release asset manifest")
    for raw_path in extra_paths:
        path = raw_path.expanduser().resolve()
        if path.parent != root:
            raise ValueError(f"Extra release asset must be directly under {root}: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
    records = _artifact_records(root)
    _write_checksums(root, records)
    records = _artifact_records(root)
    data["artifacts"] = records
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("extra", type=Path, nargs="*")
    args = parser.parse_args(argv)
    print(json.dumps(merge_release_assets(args.root, args.extra), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
