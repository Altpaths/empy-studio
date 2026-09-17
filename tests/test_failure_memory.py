from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from empy_studio.core.failure_memory import (
    MAX_AFFECTED_PATHS,
    MAX_EVIDENCE_ITEMS,
    failure_fingerprint,
    normalize_failure_text,
    normalize_relative_path,
    sanitize_failure_text,
)
from empy_studio.workspace import SQLiteWorkspaceStore


def test_fingerprint_is_stable_for_restart_values_and_paths() -> None:
    first = (
        "Verification failed at 2026-09-17T10:00:00Z, "
        "run_id=abcdef0123456789 in /Users/alice/site/index.php"
    )
    second = (
        "Verification failed at 2026-09-18T11:32:10Z, "
        "run_id=0123456789abcdef in /private/tmp/work/index.php"
    )

    assert failure_fingerprint(first, kind="verification") == failure_fingerprint(
        second, kind="verification"
    )
    assert "alice" not in normalize_failure_text(first)
    assert "<path>" in normalize_failure_text(first)


def test_sanitization_removes_credentials_and_host_paths() -> None:
    value = sanitize_failure_text(
        "api_key=sk-proj-abcdefghijklmnop in /Users/azadeh/project/config.py"
    )

    assert "sk-proj" not in value
    assert "azadeh" not in value
    assert "<redacted>" in value
    assert "<path>" in value


def test_relative_paths_reject_host_paths_and_parent_escape() -> None:
    assert normalize_relative_path("public_html\\index.php") == "public_html/index.php"
    with pytest.raises(ValueError, match="project-relative"):
        normalize_relative_path("/Users/alice/site/index.php")
    with pytest.raises(ValueError, match="inside the project"):
        normalize_relative_path("public_html/../.env")


def test_record_round_trip_deduplicates_across_tasks_and_reopens_after_resolution(
    tmp_path: Path,
) -> None:
    database = tmp_path / "workspace.sqlite3"
    store = SQLiteWorkspaceStore(database)
    first = store.record_failure(
        project_id="project-a",
        task_id="ticket-1",
        kind="ownership_mismatch",
        summary="Target file does not match project layout",
        action="Use the detected PHP entry point",
        affected_paths=("public_html/index.php",),
        evidence=("Agent report: file ownership mismatch",),
        observed_at="2026-09-17T10:00:00+00:00",
    )
    second = store.record_failure(
        project_id="project-a",
        task_id="ticket-2",
        kind="ownership_mismatch",
        summary="Target file does not match project layout",
        action="Use the detected PHP entry point",
        affected_paths=("public_html/assets/app.js",),
        observed_at="2026-09-17T10:01:00+00:00",
    )

    assert second.memory_id == first.memory_id
    assert second.occurrence_count == 2
    assert second.task_ids == ("ticket-1", "ticket-2")
    assert second.affected_paths == (
        "public_html/index.php",
        "public_html/assets/app.js",
    )

    reopened_store = SQLiteWorkspaceStore(database)
    assert reopened_store.get_failure(first.memory_id).occurrence_count == 2
    resolved = reopened_store.resolve_failure(
        first.memory_id,
        {"verified": True, "check": "pytest", "result": "passed"},
    )
    assert resolved.status == "resolved"
    assert reopened_store.find_failures("project-a") == ()
    assert reopened_store.find_failures("project-a", include_resolved=True)[0].status == "resolved"

    reopened = reopened_store.record_failure(
        project_id="project-a",
        task_id="ticket-3",
        kind="ownership_mismatch",
        summary="Target file does not match project layout",
    )
    assert reopened.memory_id == first.memory_id
    assert reopened.status == "open"
    assert reopened.occurrence_count == 3
    assert reopened.resolved_at is None
    assert reopened.resolution_evidence == ()


def test_project_isolation_and_relevant_path_matching(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    a = store.record_failure(
        project_id="project-a",
        task_id="a-ticket",
        kind="missing_asset",
        summary="Referenced asset is missing",
        affected_paths=("assets/hero.png",),
    )
    store.record_failure(
        project_id="project-b",
        task_id="b-ticket",
        kind="missing_asset",
        summary="Referenced asset is missing",
        affected_paths=("assets/hero.png",),
    )

    matches = store.find_relevant_failures(
        "project-a",
        task_id="a-ticket",
        affected_paths=("assets/hero.png",),
    )
    assert [item.memory_id for item in matches] == [a.memory_id]
    assert store.find_matching_failures("project-a", a.fingerprint)[0].memory_id == a.memory_id
    assert store.find_failures("project-a", task_id="b-ticket") == ()


def test_compact_summaries_and_context_hint_omit_raw_evidence(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    store.record_failure(
        project_id="project-a",
        kind="provider_auth",
        summary="Provider authentication is required",
        action="Configure the local provider",
        evidence=("api_key=sk-proj-abcdefghijklmnop", "raw transcript should not be copied"),
    )

    summary = store.summaries("project-a")[0]
    hint = store.context_hint("project-a")
    assert "evidence" not in summary
    assert "sk-proj" not in json.dumps(summary)
    assert "raw transcript" not in hint
    assert "Configure the local provider" in hint


def test_evidence_and_path_caps_are_enforced(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    record = store.record_failure(
        project_id="project-a",
        summary="A bounded failure",
        affected_paths=tuple(f"src/file-{index}.py" for index in range(MAX_AFFECTED_PATHS + 10)),
        evidence=tuple(f"detail-{index}" for index in range(MAX_EVIDENCE_ITEMS + 10)),
    )

    assert len(record.affected_paths) == MAX_AFFECTED_PATHS
    assert len(record.evidence) == MAX_EVIDENCE_ITEMS
    assert len(store.context_hint("project-a")) <= 2_400


def test_resolve_requires_explicit_non_empty_evidence(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    record = store.record_failure(project_id="project-a", summary="Build failed")
    with pytest.raises(ValueError, match="evidence"):
        store.resolve_failure(record.memory_id)
    with pytest.raises(ValueError, match="evidence"):
        store.resolve_failure(record.memory_id, "")
    with pytest.raises(ValueError, match="does not confirm"):
        store.resolve_failure(record.memory_id, {"verified": False, "result": "failed"})


def test_reopen_and_supersede_lifecycle(tmp_path: Path) -> None:
    store = SQLiteWorkspaceStore(tmp_path / "workspace.sqlite3")
    record = store.record_failure(project_id="project-a", summary="Old diagnosis")
    superseded = store.supersede_failure(record.memory_id, reason="A more specific check identified the cause")
    assert superseded.status == "superseded"
    with pytest.raises(ValueError, match="superseded"):
        store.resolve_failure(record.memory_id, "Verification passed")
    reopened = store.reopen_failure(record.memory_id, reason="The old symptom appeared again")
    assert reopened.status == "open"
    resolved = store.resolve_failure(record.memory_id, "Verification passed: check succeeded")
    assert resolved.status == "resolved"


def test_migration_from_schema_two_creates_empty_failure_ledger(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"
    store = SQLiteWorkspaceStore(database)
    assert store.schema_version() == 3
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
        connection.execute("DROP TABLE failure_memory")
    migrated = SQLiteWorkspaceStore(database)
    assert migrated.schema_version() == 3
    record = migrated.record_failure(project_id="project-a", summary="Migrated failure")
    assert migrated.get_failure(record.memory_id).summary == "Migrated failure"


def test_malformed_row_is_fail_closed_for_get_and_query(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"
    store = SQLiteWorkspaceStore(database)
    record = store.record_failure(project_id="project-a", summary="Stored failure")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE failure_memory SET evidence_json = ? WHERE memory_id = ?",
            ("not-json", record.memory_id),
        )
    with pytest.raises(ValueError, match="Stored failure memory row is invalid"):
        store.get_failure(record.memory_id)
    assert store.find_failures("project-a") == ()


def test_concurrent_observations_are_coalesced(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"

    def record(index: int) -> str:
        store = SQLiteWorkspaceStore(database)
        return store.record_failure(
            project_id="project-a",
            task_id=f"ticket-{index}",
            summary="Concurrent failure with run_id=abcdef0123456789",
        ).memory_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(record, range(4)))
    store = SQLiteWorkspaceStore(database)
    rows = store.find_failures("project-a")
    assert len(rows) == 1
    assert rows[0].memory_id in ids
    assert rows[0].occurrence_count == 4
