from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from empy_studio.core import ProjectDescriptor
from empy_studio.core.workspace_models import (
    WorkspaceProject,
    WorkspaceRun,
    WorkspaceTask,
    utc_now_iso,
)

SCHEMA_VERSION = 1


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
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE projects (
                    project_id TEXT PRIMARY KEY,
                    root TEXT NOT NULL UNIQUE,
                    project_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                );
                CREATE TABLE tasks (
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
                CREATE TABLE runs (
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
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX idx_tasks_project ON tasks(project_id, updated_at DESC);
                CREATE INDEX idx_runs_project ON runs(project_id, updated_at DESC);
                CREATE INDEX idx_runs_task ON runs(task_id, updated_at DESC);
                """
            )
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
