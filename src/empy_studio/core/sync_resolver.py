from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from .agent_dispatcher import AgentRunGraph

PatchOperation = Literal["create", "modify", "delete"]
PatchState = Literal["queued", "ready", "conflict", "applied", "skipped"]
ConflictKind = Literal[
    "ownership-violation",
    "protected-file",
    "stale-base",
    "duplicate-write",
    "invalid-operation",
]
ResolutionChoice = Literal["apply-patch", "keep-current", "manual-content"]
SyncStatus = Literal["ready", "blocked", "applied"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_sha256(content: str | None) -> str | None:
    if content is None:
        return None
    return _sha256_bytes(content.encode("utf-8"))


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def _normalize_relative_path(value: str) -> str:
    candidate = value.replace("\\", "/").strip()
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe patch path: {value}")
    normalized = path.as_posix()
    if normalized in {".", ""}:
        raise ValueError(f"unsafe patch path: {value}")
    return normalized


@dataclass(frozen=True)
class AgentPatch:
    patch_id: str
    node_id: str
    agent_id: str
    step_id: str
    relative_path: str
    operation: PatchOperation
    base_sha256: str | None
    content: str | None
    created_at: str
    sequence: int = 0

    def validate(self) -> None:
        if not all((self.patch_id, self.node_id, self.agent_id, self.step_id)):
            raise ValueError("patch identity cannot be empty")
        _normalize_relative_path(self.relative_path)
        if self.operation not in {"create", "modify", "delete"}:
            raise ValueError(f"unsupported patch operation: {self.operation}")
        if self.operation == "delete" and self.content is not None:
            raise ValueError("delete patches cannot contain content")
        if self.operation in {"create", "modify"} and self.content is None:
            raise ValueError("create and modify patches require content")
        if self.sequence < 0:
            raise ValueError("patch sequence cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SyncConflict:
    conflict_id: str
    patch_id: str
    relative_path: str
    kind: ConflictKind
    message: str
    current_sha256: str | None
    expected_sha256: str | None
    competing_patch_ids: tuple[str, ...] = ()
    resolution: ResolutionChoice | None = None
    manual_content: str | None = None
    resolved_at: str | None = None

    @property
    def resolved(self) -> bool:
        return self.resolution is not None

    def validate(self) -> None:
        if not all((self.conflict_id, self.patch_id, self.relative_path, self.message)):
            raise ValueError("conflict identity cannot be empty")
        if self.kind not in {
            "ownership-violation",
            "protected-file",
            "stale-base",
            "duplicate-write",
            "invalid-operation",
        }:
            raise ValueError(f"unsupported conflict kind: {self.kind}")
        if self.resolution == "manual-content" and self.manual_content is None:
            raise ValueError("manual-content resolution requires content")
        if self.resolution is None and self.resolved_at is not None:
            raise ValueError("unresolved conflict cannot have resolved_at")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PatchQueueItem:
    patch: AgentPatch
    state: PatchState
    order: int
    conflict_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "patch": self.patch.to_dict(),
            "state": self.state,
            "order": self.order,
            "conflict_ids": list(self.conflict_ids),
        }


@dataclass(frozen=True)
class SyncReport:
    schema_version: int
    sync_id: str
    graph_id: str
    project_root: str
    created_at: str
    updated_at: str
    status: SyncStatus
    queue: tuple[PatchQueueItem, ...]
    conflicts: tuple[SyncConflict, ...]
    applied_patch_ids: tuple[str, ...] = ()
    skipped_patch_ids: tuple[str, ...] = ()

    @property
    def unresolved_conflicts(self) -> tuple[SyncConflict, ...]:
        return tuple(item for item in self.conflicts if not item.resolved)

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported sync-report schema")
        if not all((self.sync_id, self.graph_id, self.project_root)):
            raise ValueError("sync report identity cannot be empty")
        patch_ids = [item.patch.patch_id for item in self.queue]
        if len(patch_ids) != len(set(patch_ids)):
            raise ValueError("patch queue IDs must be unique")
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("conflict IDs must be unique")
        known_conflicts = set(conflict_ids)
        for item in self.queue:
            item.patch.validate()
            if set(item.conflict_ids) - known_conflicts:
                raise ValueError("queue item references unknown conflict")
        for conflict in self.conflicts:
            conflict.validate()
            if conflict.patch_id not in patch_ids:
                raise ValueError("conflict references unknown patch")
        if self.status == "ready" and self.unresolved_conflicts:
            raise ValueError("ready sync report cannot contain unresolved conflicts")
        if self.status == "applied" and any(
            item.state in {"queued", "ready", "conflict"} for item in self.queue
        ):
            raise ValueError("applied report contains pending queue items")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sync_id": self.sync_id,
            "graph_id": self.graph_id,
            "project_root": self.project_root,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "queue": [item.to_dict() for item in self.queue],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "applied_patch_ids": list(self.applied_patch_ids),
            "skipped_patch_ids": list(self.skipped_patch_ids),
        }


def _conflict_id(patch_id: str, kind: ConflictKind, index: int) -> str:
    digest = hashlib.sha256(f"{patch_id}:{kind}:{index}".encode()).hexdigest()[:12]
    return f"conflict-{digest}"


def _append_sync_conflict(
    *,
    destination: list[SyncConflict],
    preceding_count: int,
    patch: AgentPatch,
    current_sha256: str | None,
    kind: ConflictKind,
    message: str,
    competing_patch_ids: tuple[str, ...] = (),
) -> None:
    destination.append(
        SyncConflict(
            conflict_id=_conflict_id(patch.patch_id, kind, preceding_count + len(destination)),
            patch_id=patch.patch_id,
            relative_path=patch.relative_path,
            kind=kind,
            message=message,
            current_sha256=current_sha256,
            expected_sha256=patch.base_sha256,
            competing_patch_ids=competing_patch_ids,
        )
    )


def build_sync_report(
    *,
    graph: AgentRunGraph,
    patches: tuple[AgentPatch, ...],
) -> SyncReport:
    graph.validate()
    root = Path(graph.project_root).expanduser().resolve()
    node_by_id = {node.node_id: node for node in graph.nodes}
    ownership = {item.relative_path: item for item in graph.ownership}
    protected = set(graph.protected_exclusions)
    node_order = {node.node_id: node.sequence for node in graph.nodes}

    validated: list[AgentPatch] = []
    for patch in patches:
        patch.validate()
        validated.append(replace(patch, relative_path=_normalize_relative_path(patch.relative_path)))
    validated.sort(key=lambda patch: (node_order.get(patch.node_id, 10**9), patch.sequence, patch.patch_id))

    path_patch_ids: dict[str, list[str]] = {}
    for patch in validated:
        path_patch_ids.setdefault(patch.relative_path, []).append(patch.patch_id)

    conflicts: list[SyncConflict] = []
    queue: list[PatchQueueItem] = []
    for order, patch in enumerate(validated, start=1):
        patch_conflicts: list[SyncConflict] = []
        target = root / patch.relative_path
        current = file_sha256(target)
        node = node_by_id.get(patch.node_id)

        if patch.relative_path in protected:
            _append_sync_conflict(
                destination=patch_conflicts,
                preceding_count=len(conflicts),
                patch=patch,
                current_sha256=current,
                kind="protected-file",
                message="Patch targets a protected file excluded from agent execution.",
            )
        if node is None or node.agent_id != patch.agent_id or node.step_id != patch.step_id:
            _append_sync_conflict(
                destination=patch_conflicts,
                preceding_count=len(conflicts),
                patch=patch,
                current_sha256=current,
                kind="ownership-violation",
                message="Patch identity does not match an agent run node.",
            )
        else:
            record = ownership.get(patch.relative_path)
            if record is None or record.owner_node_id != patch.node_id or patch.relative_path not in node.owned_files:
                _append_sync_conflict(
                    destination=patch_conflicts,
                    preceding_count=len(conflicts),
                    patch=patch,
                    current_sha256=current,
                    kind="ownership-violation",
                    message="Agent does not own the target file.",
                )

        competing = tuple(item for item in path_patch_ids[patch.relative_path] if item != patch.patch_id)
        if competing:
            _append_sync_conflict(
                destination=patch_conflicts,
                preceding_count=len(conflicts),
                patch=patch,
                current_sha256=current,
                kind="duplicate-write",
                message="Multiple agent patches target the same file.",
                competing_patch_ids=competing,
            )

        invalid = (
            (patch.operation == "create" and current is not None)
            or (patch.operation in {"modify", "delete"} and current is None)
        )
        if invalid:
            _append_sync_conflict(
                destination=patch_conflicts,
                preceding_count=len(conflicts),
                patch=patch,
                current_sha256=current,
                kind="invalid-operation",
                message="Patch operation does not match the current file state.",
            )
        elif patch.base_sha256 != current:
            _append_sync_conflict(
                destination=patch_conflicts,
                preceding_count=len(conflicts),
                patch=patch,
                current_sha256=current,
                kind="stale-base",
                message="The file changed after the agent patch was created.",
            )

        conflicts.extend(patch_conflicts)
        queue.append(
            PatchQueueItem(
                patch=patch,
                state="conflict" if patch_conflicts else "ready",
                order=order,
                conflict_ids=tuple(item.conflict_id for item in patch_conflicts),
            )
        )

    now = _utc_now()
    status: SyncStatus = "blocked" if conflicts else "ready"
    report = SyncReport(
        schema_version=1,
        sync_id=f"sync-{hashlib.sha256((graph.graph_id + now).encode()).hexdigest()[:16]}",
        graph_id=graph.graph_id,
        project_root=str(root),
        created_at=now,
        updated_at=now,
        status=status,
        queue=tuple(queue),
        conflicts=tuple(conflicts),
    )
    report.validate()
    return report


def resolve_sync_conflict(
    report: SyncReport,
    *,
    conflict_id: str,
    choice: ResolutionChoice,
    manual_content: str | None = None,
) -> SyncReport:
    if choice not in {"apply-patch", "keep-current", "manual-content"}:
        raise ValueError(f"unsupported resolution choice: {choice}")
    conflicts: list[SyncConflict] = []
    found = False
    for conflict in report.conflicts:
        if conflict.conflict_id != conflict_id:
            conflicts.append(conflict)
            continue
        found = True
        conflicts.append(
            replace(
                conflict,
                resolution=choice,
                manual_content=manual_content if choice == "manual-content" else None,
                resolved_at=_utc_now(),
            )
        )
    if not found:
        raise KeyError(f"unknown sync conflict: {conflict_id}")

    by_id = {item.conflict_id: item for item in conflicts}
    queue: list[PatchQueueItem] = []
    for item in report.queue:
        related = [by_id[value] for value in item.conflict_ids]
        if related and all(conflict.resolved for conflict in related):
            choices = {conflict.resolution for conflict in related}
            state: PatchState = "skipped" if "keep-current" in choices else "ready"
            queue.append(replace(item, state=state))
        else:
            queue.append(item)
    unresolved = [item for item in conflicts if not item.resolved]
    status: SyncStatus = "blocked" if unresolved else "ready"
    updated = replace(
        report,
        updated_at=_utc_now(),
        status=status,
        queue=tuple(queue),
        conflicts=tuple(conflicts),
    )
    updated.validate()
    return updated


def apply_sync_report(report: SyncReport) -> SyncReport:
    report.validate()
    if report.unresolved_conflicts:
        raise ValueError("sync is blocked by unresolved conflicts")
    if report.status != "ready":
        raise ValueError("sync report is not ready to apply")

    root = Path(report.project_root).expanduser().resolve()
    conflicts_by_patch: dict[str, list[SyncConflict]] = {}
    for conflict in report.conflicts:
        conflicts_by_patch.setdefault(conflict.patch_id, []).append(conflict)

    operations: list[tuple[PatchQueueItem, str | None]] = []
    skipped: list[str] = []
    for item in sorted(report.queue, key=lambda value: value.order):
        if item.state == "skipped":
            skipped.append(item.patch.patch_id)
            continue
        related = conflicts_by_patch.get(item.patch.patch_id, [])
        manual = next((value.manual_content for value in related if value.resolution == "manual-content"), None)
        content = manual if manual is not None else item.patch.content
        operations.append((item, content))

    # Revalidate all non-overridden bases before touching the workspace.
    for item, _ in operations:
        related = conflicts_by_patch.get(item.patch.patch_id, [])
        forced = any(value.resolution in {"apply-patch", "manual-content"} for value in related)
        current = file_sha256(root / item.patch.relative_path)
        if not forced and current != item.patch.base_sha256:
            raise ValueError(f"workspace changed before apply: {item.patch.relative_path}")

    backups: dict[Path, bytes | None] = {}
    applied: list[str] = []
    try:
        for item, content in operations:
            target = root / item.patch.relative_path
            backups.setdefault(target, target.read_bytes() if target.is_file() else None)
            if item.patch.operation == "delete":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                encoded = (content or "").encode("utf-8")
                handle, temporary_name = tempfile.mkstemp(prefix=".empy-sync-", dir=str(target.parent))
                try:
                    with os.fdopen(handle, "wb") as temporary:
                        temporary.write(encoded)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    os.replace(temporary_name, target)
                finally:
                    if os.path.exists(temporary_name):
                        os.unlink(temporary_name)
            applied.append(item.patch.patch_id)
    except Exception:
        for target, previous in backups.items():
            if previous is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(previous)
        raise

    applied_ids = set(applied)
    queue = tuple(
        replace(item, state="applied") if item.patch.patch_id in applied_ids else item
        for item in report.queue
    )
    final = replace(
        report,
        updated_at=_utc_now(),
        status="applied",
        queue=queue,
        applied_patch_ids=tuple(applied),
        skipped_patch_ids=tuple(skipped),
    )
    final.validate()
    return final
