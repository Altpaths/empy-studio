from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from empy_studio.core import ProjectDescriptor
from empy_studio.core.failure_memory import (
    MAX_CONTEXT_HINT_CHARS,
    MAX_EVIDENCE_CHARS,
    MAX_MEMORY_ROWS_PER_PROJECT,
    MAX_QUERY_LIMIT,
    FailureMemoryRecord,
    _normalize_evidence,
    failure_fingerprint,
    normalize_affected_paths,
    normalize_supplied_fingerprint,
    sanitize_failure_text,
    validate_verification_evidence,
)
from empy_studio.core.workspace_models import (
    WorkspaceProject,
    WorkspaceRelease,
    WorkspaceRun,
    WorkspaceTask,
    utc_now_iso,
)

SCHEMA_VERSION = 3


def default_workspace_path() -> Path:
    override = os.environ.get("EMPY_WORKSPACE_PATH")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif os.uname().sysname == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return (base / "Empy Studio" / "workspace.sqlite3").resolve()


class SQLiteWorkspaceStore:
    """Versioned local persistence for projects, tasks, runs, and settings."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path).expanduser().resolve()
            if database_path is not None
            else default_workspace_path()
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row is not None else 0
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    "Workspace schema is newer than this Empy Studio build"
                )
            self._migrate(connection, current)

    def _migrate(self, connection: sqlite3.Connection, current: int) -> None:
        if current < 1:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    root TEXT NOT NULL UNIQUE,
                    project_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    state TEXT NOT NULL,
                    driver_name TEXT,
                    summary TEXT NOT NULL,
                    evidence_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, updated_at DESC);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '1')"
            )
            current = 1
        if current < 2:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    release_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    archive_path TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    checksum_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    verified INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_releases_project ON releases(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_releases_task ON releases(task_id, created_at DESC);
                """
            )
            current = 2
        if current < 3:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS failure_memory (
                    memory_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_id TEXT,
                    fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    action TEXT NOT NULL,
                    affected_paths_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'superseded')),
                    occurrence_count INTEGER NOT NULL CHECK(occurrence_count >= 1),
                    task_ids_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution_evidence_json TEXT NOT NULL,
                    superseded_by TEXT,
                    UNIQUE(project_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_failure_memory_project
                    ON failure_memory(project_id, status, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_failure_memory_fingerprint
                    ON failure_memory(project_id, fingerprint);
                """
            )
            current = 3
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def schema_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        if row is None:
            raise RuntimeError("Workspace schema metadata is missing")
        return int(row["value"])

    def save_project(self, project: ProjectDescriptor) -> WorkspaceProject:
        project.validate()
        root = str(project.root.expanduser().resolve())
        now = utc_now_iso()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT project_id, created_at FROM projects WHERE root = ?",
                (root,),
            ).fetchone()
            project_id = (
                str(existing["project_id"])
                if existing is not None
                else uuid.uuid4().hex
            )
            created_at = (
                str(existing["created_at"])
                if existing is not None
                else now
            )
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, root, project_type, display_name,
                    created_at, updated_at, last_opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root) DO UPDATE SET
                    project_type = excluded.project_type,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    project_id,
                    root,
                    project.project_type,
                    project.display_name,
                    created_at,
                    now,
                    now,
                ),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> WorkspaceProject:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return self._project_from_row(row)

    def list_projects(self) -> tuple[WorkspaceProject, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY last_opened_at DESC"
            ).fetchall()
        return tuple(self._project_from_row(row) for row in rows)

    def remove_project(self, project_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM failure_memory WHERE project_id = ?",
                (project_id,),
            )
            result = connection.execute(
                "DELETE FROM projects WHERE project_id = ?",
                (project_id,),
            )
        if result.rowcount == 0:
            raise KeyError(project_id)

    def create_task(
        self,
        *,
        project_id: str,
        title: str,
        request_text: str,
        task_kind: str,
        contract: Mapping[str, Any],
        status: str = "draft",
        task_id: str | None = None,
    ) -> WorkspaceTask:
        selected_id = task_id or uuid.uuid4().hex
        now = utc_now_iso()
        task = WorkspaceTask(
            task_id=selected_id,
            project_id=project_id,
            title=title,
            request_text=request_text,
            task_kind=task_kind,
            status=status,
            contract=dict(contract),
            created_at=now,
            updated_at=now,
        )
        task.validate()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, project_id, title, request_text, task_kind,
                    status, contract_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.project_id,
                    task.title,
                    task.request_text,
                    task.task_kind,
                    task.status,
                    json.dumps(task.contract, ensure_ascii=False, sort_keys=True),
                    task.created_at,
                    task.updated_at,
                ),
            )
        return task

    def get_task(self, task_id: str) -> WorkspaceTask:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, project_id: str) -> tuple[WorkspaceTask, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return tuple(self._task_from_row(row) for row in rows)

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        request_text: str | None = None,
        task_kind: str | None = None,
        status: str | None = None,
        contract: Mapping[str, Any] | None = None,
    ) -> WorkspaceTask:
        current = self.get_task(task_id)
        updated = WorkspaceTask(
            task_id=current.task_id,
            project_id=current.project_id,
            title=title if title is not None else current.title,
            request_text=request_text if request_text is not None else current.request_text,
            task_kind=task_kind if task_kind is not None else current.task_kind,
            status=status if status is not None else current.status,
            contract=dict(contract) if contract is not None else current.contract,
            created_at=current.created_at,
            updated_at=utc_now_iso(),
        )
        updated.validate()
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE tasks SET title = ?, request_text = ?, task_kind = ?,
                    status = ?, contract_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    updated.title,
                    updated.request_text,
                    updated.task_kind,
                    updated.status,
                    json.dumps(updated.contract, ensure_ascii=False, sort_keys=True),
                    updated.updated_at,
                    task_id,
                ),
            )
        if result.rowcount == 0:
            raise KeyError(task_id)
        return self.get_task(task_id)

    def create_run(
        self,
        *,
        task_id: str,
        project_id: str,
        summary: str,
        state: str = "planned",
        driver_name: str | None = None,
        evidence_path: str | None = None,
        run_id: str | None = None,
    ) -> WorkspaceRun:
        selected_id = run_id or uuid.uuid4().hex
        now = utc_now_iso()
        run = WorkspaceRun(
            run_id=selected_id,
            task_id=task_id,
            project_id=project_id,
            state=state,  # type: ignore[arg-type]
            driver_name=driver_name,
            summary=summary,
            evidence_path=evidence_path,
            created_at=now,
            updated_at=now,
        )
        run.validate()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, task_id, project_id, state, driver_name,
                    summary, evidence_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.task_id,
                    run.project_id,
                    run.state,
                    run.driver_name,
                    run.summary,
                    run.evidence_path,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def update_run(
        self,
        run_id: str,
        *,
        state: str,
        summary: str,
        driver_name: str | None = None,
        evidence_path: str | None = None,
    ) -> WorkspaceRun:
        now = utc_now_iso()
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE runs SET state = ?, summary = ?, driver_name = ?,
                    evidence_path = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (state, summary, driver_name, evidence_path, now, run_id),
            )
        if result.rowcount == 0:
            raise KeyError(run_id)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> WorkspaceRun:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run_from_row(row)

    def list_runs(self, project_id: str) -> tuple[WorkspaceRun, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def list_task_runs(self, task_id: str) -> tuple[WorkspaceRun, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE task_id = ? ORDER BY updated_at DESC",
                (task_id,),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def record_failure(
        self,
        *,
        project_id: str,
        summary: str,
        kind: str = "unknown",
        action: str = "",
        task_id: str | None = None,
        affected_paths: Sequence[str] = (),
        evidence: Sequence[str] = (),
        fingerprint: str | None = None,
        observed_at: str | None = None,
    ) -> FailureMemoryRecord:
        """Record one bounded incident, coalescing an existing project match.

        A fingerprint is unique within a project.  A later ticket that sees
        the same fingerprint increments the occurrence count and reopens a
        previously resolved/superseded record, so stale success cannot hide a
        newly observed regression.
        """

        project_id = self._failure_identifier(project_id, "project_id", 256)
        if task_id is not None:
            task_id = self._failure_identifier(task_id, "task_id", 256)
        safe_kind = sanitize_failure_text(kind, max_chars=80)
        safe_summary = sanitize_failure_text(summary, max_chars=800)
        safe_action = sanitize_failure_text(action, max_chars=800)
        safe_paths = normalize_affected_paths(affected_paths)
        safe_evidence = _normalize_evidence(evidence)
        safe_fingerprint = (
            normalize_supplied_fingerprint(fingerprint)
            if fingerprint is not None
            else failure_fingerprint(
                safe_summary,
                kind=safe_kind,
                action=safe_action,
                evidence=safe_evidence,
            )
        )
        timestamp = self._failure_timestamp(observed_at)

        with self._connection() as connection:
            # Serialize the read/merge/write sequence.  Without an immediate
            # transaction two fresh processes can both observe no row and
            # race on the project/fingerprint UNIQUE constraint.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM failure_memory
                WHERE project_id = ? AND fingerprint = ?
                """,
                (project_id, safe_fingerprint),
            ).fetchone()
            if row is None:
                record = FailureMemoryRecord(
                    memory_id=uuid.uuid4().hex,
                    project_id=project_id,
                    task_id=task_id,
                    fingerprint=safe_fingerprint,
                    kind=safe_kind,
                    summary=safe_summary,
                    action=safe_action,
                    affected_paths=safe_paths,
                    evidence=safe_evidence,
                    status="open",
                    occurrence_count=1,
                    task_ids=(task_id,) if task_id is not None else (),
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                )
                record.validate()
                self._insert_failure(connection, record)
                memory_id = record.memory_id
            else:
                current = self._failure_from_row(row)
                merged_paths = normalize_affected_paths(
                    (*current.affected_paths, *safe_paths)
                )
                merged_evidence = _normalize_evidence(
                    (*current.evidence, *safe_evidence)
                )
                merged_task_ids = self._merge_task_ids(current.task_ids, task_id)
                record = FailureMemoryRecord(
                    memory_id=current.memory_id,
                    project_id=current.project_id,
                    task_id=task_id or current.task_id,
                    fingerprint=current.fingerprint,
                    kind=safe_kind or current.kind,
                    summary=safe_summary or current.summary,
                    action=safe_action or current.action,
                    affected_paths=merged_paths,
                    evidence=merged_evidence,
                    status="open",
                    occurrence_count=current.occurrence_count + 1,
                    task_ids=merged_task_ids,
                    first_seen_at=current.first_seen_at,
                    last_seen_at=timestamp,
                )
                record.validate()
                self._update_failure(connection, record)
                memory_id = record.memory_id
            self._prune_failure_memory(
                connection,
                project_id=project_id,
                protected_memory_id=memory_id,
            )
            saved = connection.execute(
                "SELECT * FROM failure_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if saved is None:
            # The protected row is never pruned.  This guard also makes a
            # damaged database fail closed instead of returning a false record.
            raise RuntimeError("Failure memory record disappeared during save")
        return self._failure_from_row(saved)

    def get_failure(self, memory_id: str) -> FailureMemoryRecord:
        memory_id = self._failure_identifier(memory_id, "memory_id", 256)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM failure_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._failure_from_row(row)

    def find_failures(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        fingerprint: str | None = None,
        affected_paths: Sequence[str] = (),
        kind: str | None = None,
        include_resolved: bool = False,
        limit: int = 20,
    ) -> tuple[FailureMemoryRecord, ...]:
        """Find project-local failures without reading provider transcripts."""

        project_id = self._failure_identifier(project_id, "project_id", 256)
        if task_id is not None:
            task_id = self._failure_identifier(task_id, "task_id", 256)
        if type(include_resolved) is not bool:
            raise TypeError("include_resolved must be a boolean")
        if type(limit) is not int or not 1 <= limit <= MAX_QUERY_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_QUERY_LIMIT}")
        requested_paths = set(normalize_affected_paths(affected_paths))
        requested_kind = (
            sanitize_failure_text(kind, max_chars=80).casefold()
            if kind is not None
            else None
        )
        requested_fingerprint = (
            normalize_supplied_fingerprint(fingerprint)
            if fingerprint is not None
            else None
        )
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM failure_memory
                WHERE project_id = ?
                  AND (? = 1 OR status = 'open')
                ORDER BY last_seen_at DESC, memory_id ASC
                """,
                (project_id, int(include_resolved)),
            ).fetchall()
        matches: list[tuple[int, FailureMemoryRecord]] = []
        for row in rows:
            try:
                record = self._failure_from_row(row)
            except (TypeError, ValueError, KeyError):
                # Corrupt persisted diagnostics are ignored rather than
                # surfaced as raw SQLite/JSON errors to the user.
                continue
            if requested_fingerprint is not None and record.fingerprint != requested_fingerprint:
                continue
            if task_id is not None and task_id not in record.task_ids:
                continue
            if requested_kind is not None and record.kind.casefold() != requested_kind:
                continue
            overlap = len(requested_paths.intersection(record.affected_paths))
            if requested_paths and overlap == 0:
                continue
            score = (
                (10_000 if requested_fingerprint is not None else 0)
                + (1_000 if task_id is not None and task_id in record.task_ids else 0)
                + (100 * overlap)
                + (10 if requested_kind is not None else 0)
            )
            matches.append((score, record))
        # Keep score precedence while returning newer observations first
        # within an equally relevant group.
        matches.sort(key=lambda item: item[1].memory_id)
        matches.sort(key=lambda item: item[1].last_seen_at, reverse=True)
        matches.sort(key=lambda item: item[0], reverse=True)
        return tuple(record for _, record in matches[:limit])

    def find_matching_failures(
        self,
        project_id: str,
        fingerprint: str,
        *,
        task_id: str | None = None,
        include_resolved: bool = False,
        limit: int = 20,
    ) -> tuple[FailureMemoryRecord, ...]:
        """Return exact project/fingerprint matches, including old tickets."""

        return self.find_failures(
            project_id,
            task_id=task_id,
            fingerprint=fingerprint,
            include_resolved=include_resolved,
            limit=limit,
        )

    def find_relevant_failures(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        fingerprint: str | None = None,
        affected_paths: Sequence[str] = (),
        kind: str | None = None,
        include_resolved: bool = False,
        limit: int = 20,
    ) -> tuple[FailureMemoryRecord, ...]:
        """Return matching or path/kind-related open project incidents."""

        return self.find_failures(
            project_id,
            task_id=task_id,
            fingerprint=fingerprint,
            affected_paths=affected_paths,
            kind=kind,
            include_resolved=include_resolved,
            limit=limit,
        )

    def list_failures(
        self,
        project_id: str,
        *,
        include_resolved: bool = False,
        limit: int = 20,
    ) -> tuple[FailureMemoryRecord, ...]:
        """Compatibility alias for callers that use list terminology."""

        return self.find_failures(
            project_id,
            include_resolved=include_resolved,
            limit=limit,
        )

    def failure_summaries(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        fingerprint: str | None = None,
        affected_paths: Sequence[str] = (),
        kind: str | None = None,
        include_resolved: bool = False,
        limit: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        """Return compact, prompt/UI-safe dictionaries without raw evidence."""

        records = self.find_failures(
            project_id,
            task_id=task_id,
            fingerprint=fingerprint,
            affected_paths=affected_paths,
            kind=kind,
            include_resolved=include_resolved,
            limit=limit,
        )
        return tuple(record.compact_summary() for record in records)

    # ``summaries`` is intentionally short for the GuidedState integration.
    summaries = failure_summaries

    def failure_context_hint(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        fingerprint: str | None = None,
        affected_paths: Sequence[str] = (),
        kind: str | None = None,
        include_resolved: bool = False,
        limit: int = 8,
    ) -> str:
        """Render a bounded text handoff for a later ticket or recovery run."""

        summaries = self.failure_summaries(
            project_id,
            task_id=task_id,
            fingerprint=fingerprint,
            affected_paths=affected_paths,
            kind=kind,
            include_resolved=include_resolved,
            limit=limit,
        )
        if not summaries:
            return ""
        lines = ["Known project failure memory (use as evidence; do not rediscover):"]
        for item in summaries:
            paths = ", ".join(item["affected_paths"][:8]) or "none recorded"
            lines.append(
                f"- [{item['status']}] {item['kind']}: {item['summary']} "
                f"Action: {item['action'] or 'review the recorded evidence'} "
                f"Files: {paths} Occurrences: {item['occurrence_count']}"
            )
        text = " ".join(lines)
        return text[:MAX_CONTEXT_HINT_CHARS].rstrip()

    context_hint = failure_context_hint

    def resolve_failure(
        self,
        memory_id: str,
        verification_evidence: str | Mapping[str, Any] | Sequence[str] | None = None,
        *,
        verification_id: str | None = None,
    ) -> FailureMemoryRecord:
        """Resolve only with explicit bounded evidence from a successful check."""

        memory_id = self._failure_identifier(memory_id, "memory_id", 256)
        evidence = list(validate_verification_evidence(verification_evidence))
        if verification_id is not None:
            verification_id = self._failure_identifier(verification_id, "verification_id", 256)
            evidence = list(_normalize_evidence((*evidence, f"verification_id: {verification_id}")))
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM failure_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            current = self._failure_from_row(row)
            if current.status == "superseded":
                raise ValueError("superseded failure memory cannot be resolved")
            connection.execute(
                """
                UPDATE failure_memory
                SET status = 'resolved', resolved_at = ?,
                    resolution_evidence_json = ?, superseded_by = NULL
                WHERE memory_id = ?
                """,
                (
                    utc_now_iso(),
                    json.dumps(evidence, ensure_ascii=False),
                    memory_id,
                ),
            )
        return self.get_failure(memory_id)

    # Explicit aliases keep the API readable at call sites and accommodate
    # the terminology used by older GuidedState prototypes.
    mark_resolved = resolve_failure
    mark_failure_resolved = resolve_failure

    def reopen_failure(self, memory_id: str, *, reason: str) -> FailureMemoryRecord:
        """Reopen a stale resolution after a new, explicit observation."""

        memory_id = self._failure_identifier(memory_id, "memory_id", 256)
        safe_reason = sanitize_failure_text(reason, max_chars=MAX_EVIDENCE_CHARS)
        if not safe_reason:
            raise ValueError("reopen reason cannot be empty")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM failure_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            current = self._failure_from_row(row)
            evidence = _normalize_evidence((*current.evidence, f"reopened: {safe_reason}"))
            connection.execute(
                """
                UPDATE failure_memory
                SET status = 'open', last_seen_at = ?, resolved_at = NULL,
                    resolution_evidence_json = '[]', superseded_by = NULL,
                    evidence_json = ?
                WHERE memory_id = ?
                """,
                (utc_now_iso(), json.dumps(evidence, ensure_ascii=False), memory_id),
            )
        return self.get_failure(memory_id)

    def supersede_failure(
        self,
        memory_id: str,
        *,
        replacement_id: str | None = None,
        reason: str | None = None,
    ) -> FailureMemoryRecord:
        """Mark an incident replaced by a more specific diagnosis."""

        memory_id = self._failure_identifier(memory_id, "memory_id", 256)
        if replacement_id is not None:
            replacement_id = self._failure_identifier(replacement_id, "replacement_id", 256)
            if replacement_id == memory_id:
                raise ValueError("a failure cannot supersede itself")
        safe_reason = (
            sanitize_failure_text(reason, max_chars=MAX_EVIDENCE_CHARS)
            if reason is not None
            else ""
        )
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM failure_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            evidence = list(self._failure_from_row(row).evidence)
            if safe_reason:
                evidence = list(_normalize_evidence((*evidence, f"superseded: {safe_reason}")))
            connection.execute(
                """
                UPDATE failure_memory
                SET status = 'superseded', resolved_at = NULL,
                    resolution_evidence_json = '[]', superseded_by = ?,
                    evidence_json = ?
                WHERE memory_id = ?
                """,
                (
                    replacement_id,
                    json.dumps(evidence, ensure_ascii=False),
                    memory_id,
                ),
            )
        return self.get_failure(memory_id)

    def create_release(
        self,
        *,
        task_id: str,
        project_id: str,
        archive_path: str,
        manifest_path: str,
        checksum_path: str,
        sha256: str,
        file_count: int,
        verified: bool,
        release_id: str | None = None,
    ) -> WorkspaceRelease:
        release = WorkspaceRelease(
            release_id=release_id or uuid.uuid4().hex,
            task_id=task_id,
            project_id=project_id,
            archive_path=archive_path,
            manifest_path=manifest_path,
            checksum_path=checksum_path,
            sha256=sha256,
            file_count=file_count,
            verified=verified,
            created_at=utc_now_iso(),
        )
        release.validate()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO releases(
                    release_id, task_id, project_id, archive_path, manifest_path,
                    checksum_path, sha256, file_count, verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release.release_id,
                    release.task_id,
                    release.project_id,
                    release.archive_path,
                    release.manifest_path,
                    release.checksum_path,
                    release.sha256,
                    release.file_count,
                    int(release.verified),
                    release.created_at,
                ),
            )
        return release

    def list_releases(self, project_id: str) -> tuple[WorkspaceRelease, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM releases WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return tuple(self._release_from_row(row) for row in rows)

    def list_task_releases(self, task_id: str) -> tuple[WorkspaceRelease, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM releases WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
        return tuple(self._release_from_row(row) for row in rows)

    def set_setting(self, key: str, value: Any) -> None:
        if not key.strip():
            raise ValueError("setting key cannot be empty")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
        return default if row is None else json.loads(str(row["value_json"]))

    @staticmethod
    def _failure_identifier(value: str, name: str, max_chars: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        value = value.strip()
        if not value:
            raise ValueError(f"{name} cannot be empty")
        if len(value) > max_chars:
            raise ValueError(f"{name} cannot exceed {max_chars} characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{name} contains control characters")
        if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise ValueError(f"{name} must be an opaque identifier")
        return value

    @staticmethod
    def _failure_timestamp(value: str | None) -> str:
        if value is None:
            return utc_now_iso()
        if not isinstance(value, str):
            raise TypeError("observed_at must be a string")
        value = value.strip()
        if not value or len(value) > 80:
            raise ValueError("observed_at must be a non-empty timestamp")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("observed_at contains control characters")
        return value

    @staticmethod
    def _merge_task_ids(
        existing: Sequence[str],
        task_id: str | None,
    ) -> tuple[str, ...]:
        values = list(existing)
        if task_id is not None and task_id not in values:
            values.append(task_id)
        # Keep the most recent task IDs: the current task is appended above and
        # old provenance is bounded instead of growing forever.
        return tuple(values[-32:])

    @staticmethod
    def _insert_failure(
        connection: sqlite3.Connection,
        record: FailureMemoryRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO failure_memory(
                memory_id, project_id, task_id, fingerprint, kind, summary,
                action, affected_paths_json, evidence_json, status,
                occurrence_count, task_ids_json, first_seen_at, last_seen_at,
                resolved_at, resolution_evidence_json, superseded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.memory_id,
                record.project_id,
                record.task_id,
                record.fingerprint,
                record.kind,
                record.summary,
                record.action,
                json.dumps(record.affected_paths, ensure_ascii=False),
                json.dumps(record.evidence, ensure_ascii=False),
                record.status,
                record.occurrence_count,
                json.dumps(record.task_ids, ensure_ascii=False),
                record.first_seen_at,
                record.last_seen_at,
                record.resolved_at,
                json.dumps(record.resolution_evidence, ensure_ascii=False),
                record.superseded_by,
            ),
        )

    @staticmethod
    def _update_failure(
        connection: sqlite3.Connection,
        record: FailureMemoryRecord,
    ) -> None:
        result = connection.execute(
            """
            UPDATE failure_memory SET
                project_id = ?, task_id = ?, fingerprint = ?, kind = ?,
                summary = ?, action = ?, affected_paths_json = ?,
                evidence_json = ?, status = ?, occurrence_count = ?,
                task_ids_json = ?, first_seen_at = ?, last_seen_at = ?,
                resolved_at = ?, resolution_evidence_json = ?, superseded_by = ?
            WHERE memory_id = ?
            """,
            (
                record.project_id,
                record.task_id,
                record.fingerprint,
                record.kind,
                record.summary,
                record.action,
                json.dumps(record.affected_paths, ensure_ascii=False),
                json.dumps(record.evidence, ensure_ascii=False),
                record.status,
                record.occurrence_count,
                json.dumps(record.task_ids, ensure_ascii=False),
                record.first_seen_at,
                record.last_seen_at,
                record.resolved_at,
                json.dumps(record.resolution_evidence, ensure_ascii=False),
                record.superseded_by,
                record.memory_id,
            ),
        )
        if result.rowcount == 0:
            raise KeyError(record.memory_id)

    @staticmethod
    def _prune_failure_memory(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        protected_memory_id: str,
    ) -> None:
        rows = connection.execute(
            "SELECT memory_id, status FROM failure_memory WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        excess = len(rows) - MAX_MEMORY_ROWS_PER_PROJECT
        if excess <= 0:
            return
        rank = {"resolved": 0, "superseded": 1, "open": 2}
        candidates = sorted(
            (
                row
                for row in rows
                if str(row["memory_id"]) != protected_memory_id
            ),
            key=lambda row: (rank.get(str(row["status"]), 3), str(row["memory_id"])),
        )
        for row in candidates[:excess]:
            connection.execute(
                "DELETE FROM failure_memory WHERE memory_id = ?",
                (str(row["memory_id"]),),
            )

    @staticmethod
    def _failure_from_row(row: sqlite3.Row) -> FailureMemoryRecord:
        try:
            affected_paths = json.loads(str(row["affected_paths_json"]))
            evidence = json.loads(str(row["evidence_json"]))
            task_ids = json.loads(str(row["task_ids_json"]))
            resolution_evidence = json.loads(str(row["resolution_evidence_json"]))
            if not all(
                isinstance(value, list)
                for value in (affected_paths, evidence, task_ids, resolution_evidence)
            ):
                raise ValueError("failure memory JSON columns must be arrays")
            record = FailureMemoryRecord(
                memory_id=str(row["memory_id"]),
                project_id=str(row["project_id"]),
                task_id=(str(row["task_id"]) if row["task_id"] is not None else None),
                fingerprint=str(row["fingerprint"]),
                kind=str(row["kind"]),
                summary=str(row["summary"]),
                action=str(row["action"]),
                affected_paths=tuple(str(item) for item in affected_paths),
                evidence=tuple(str(item) for item in evidence),
                status=str(row["status"]),  # type: ignore[arg-type]
                occurrence_count=int(row["occurrence_count"]),
                task_ids=tuple(str(item) for item in task_ids),
                first_seen_at=str(row["first_seen_at"]),
                last_seen_at=str(row["last_seen_at"]),
                resolved_at=(str(row["resolved_at"]) if row["resolved_at"] is not None else None),
                resolution_evidence=tuple(str(item) for item in resolution_evidence),
                superseded_by=(
                    str(row["superseded_by"])
                    if row["superseded_by"] is not None
                    else None
                ),
            )
            record.validate()
            return record
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("Stored failure memory row is invalid") from exc

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> WorkspaceProject:
        return WorkspaceProject(
            project_id=str(row["project_id"]),
            root=str(row["root"]),
            project_type=str(row["project_type"]),
            display_name=str(row["display_name"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_opened_at=str(row["last_opened_at"]),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> WorkspaceTask:
        return WorkspaceTask(
            task_id=str(row["task_id"]),
            project_id=str(row["project_id"]),
            title=str(row["title"]),
            request_text=str(row["request_text"]),
            task_kind=str(row["task_kind"]),
            status=str(row["status"]),
            contract=json.loads(str(row["contract_json"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> WorkspaceRun:
        return WorkspaceRun(
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            project_id=str(row["project_id"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            driver_name=(
                str(row["driver_name"])
                if row["driver_name"] is not None
                else None
            ),
            summary=str(row["summary"]),
            evidence_path=(
                str(row["evidence_path"])
                if row["evidence_path"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _release_from_row(row: sqlite3.Row) -> WorkspaceRelease:
        return WorkspaceRelease(
            release_id=str(row["release_id"]),
            task_id=str(row["task_id"]),
            project_id=str(row["project_id"]),
            archive_path=str(row["archive_path"]),
            manifest_path=str(row["manifest_path"]),
            checksum_path=str(row["checksum_path"]),
            sha256=str(row["sha256"]),
            file_count=int(row["file_count"]),
            verified=bool(row["verified"]),
            created_at=str(row["created_at"]),
        )
