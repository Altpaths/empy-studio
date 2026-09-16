"""Immutable context snapshots used to avoid repeating project discovery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .context_selector import ContextSelection


@dataclass(frozen=True)
class ContextManifestFile:
    relative_path: str
    sha256: str
    selected_bytes: int
    content_included: bool

    def validate(self) -> None:
        if not self.relative_path or len(self.sha256) != 64:
            raise ValueError("context manifest file identity is invalid")
        if self.selected_bytes < 0:
            raise ValueError("context manifest selected bytes cannot be negative")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class ContextManifest:
    """Content-addressed project context identity.

    The manifest contains hashes and sizes only.  A provider continuation can
    refer to this identity and receive an exact diff/handoff without being
    sent the entire original context again.
    """

    schema_version: int
    project_root: str
    selection_id: str
    snapshot_sha256: str
    files: tuple[ContextManifestFile, ...]
    selected_bytes: int

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported context manifest schema")
        if not self.project_root or not self.selection_id or len(self.snapshot_sha256) != 64:
            raise ValueError("context manifest identity is invalid")
        if self.selected_bytes < 0:
            raise ValueError("context manifest selected bytes cannot be negative")
        paths = []
        for item in self.files:
            item.validate()
            paths.append(item.relative_path)
        if paths != sorted(set(paths)):
            raise ValueError("context manifest paths must be unique and sorted")
        if sum(item.selected_bytes for item in self.files) != self.selected_bytes:
            raise ValueError("context manifest byte count is inconsistent")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            **asdict(self),
            "files": [item.to_dict() for item in self.files],
        }

    def compact_reference(self) -> str:
        self.validate()
        return (
            f"Context snapshot {self.snapshot_sha256[:20]} contains "
            f"{len(self.files)} selected files ({self.selected_bytes} bytes). "
            "Use the exact selected paths and do not rediscover the project."
        )

    def handoff(self, *, changed_files: tuple[str, ...] = (), summary: str = "") -> str:
        """Render a bounded continuation handoff without source contents."""

        changed = ", ".join(changed_files[:20]) or "none"
        detail = " ".join(summary.strip().split())[:1200] or "none"
        return (
            f"Context snapshot: {self.snapshot_sha256}\n"
            f"Changed files: {changed}\n"
            f"Previous worker report (untrusted): {detail}"
        )

    @classmethod
    def from_selection(cls, selection: ContextSelection) -> ContextManifest:
        selection.validate()
        values: dict[str, ContextManifestFile] = {}
        for pack in selection.packs:
            for item in pack.files:
                key = item.relative_path
                existing = values.get(key)
                candidate = ContextManifestFile(
                    relative_path=key,
                    sha256=item.sha256,
                    selected_bytes=item.included_bytes,
                    content_included=bool(item.content),
                )
                if existing is None:
                    values[key] = candidate
                elif existing.sha256 != candidate.sha256:
                    raise ValueError(f"context file has conflicting hashes: {key}")
                else:
                    values[key] = ContextManifestFile(
                        relative_path=key,
                        sha256=existing.sha256,
                        selected_bytes=max(existing.selected_bytes, candidate.selected_bytes),
                        content_included=existing.content_included or candidate.content_included,
                    )
        files = tuple(values[key] for key in sorted(values))
        payload = json.dumps(
            {
                "project_root": str(Path(selection.project_root).expanduser().resolve()),
                "selection_id": selection.selection_id,
                "files": [item.to_dict() for item in files],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest = cls(
            schema_version=1,
            project_root=str(Path(selection.project_root).expanduser().resolve()),
            selection_id=selection.selection_id,
            snapshot_sha256=hashlib.sha256(payload).hexdigest(),
            files=files,
            selected_bytes=sum(item.selected_bytes for item in files),
        )
        manifest.validate()
        return manifest
