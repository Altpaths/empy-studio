from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from empy_studio.drivers import (
    CodexGraphExecution,
    CodexInstallation,
    CodexNodeExecution,
    CodexWaveExecution,
)
from empy_studio.project_delivery import ExportedProject
from empy_studio.review_workspace import ReviewReport
from empy_studio.token_usage import TokenUsage
from empy_studio.verification_pipeline import VerificationCheck, VerificationReport, VerificationResult
from empy_studio.web_desktop import GuidedState, RequestHandler, _failure_kind, create_server


def test_guided_state_persists_project_and_follow_up_ticket(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n",
        encoding="utf-8",
    )
    (source / "src").mkdir()
    (source / "src" / "service.py").write_text(
        "def run():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (source / "tests").mkdir()
    (source / "tests" / "test_service.py").write_text(
        "def test_run():\n    assert True\n",
        encoding="utf-8",
    )

    first = GuidedState(tmp_path / "empy-workspace")
    first.import_path(str(source))
    first.create_plan("Update the backend service\nRun the service tests")

    assert first.active_project_id is not None
    assert first.active_task_id is not None
    first_task_id = first.active_task_id
    assert first.phase == "plan"
    assert first.plan is not None
    assert any(node.owned_files for node in first.graph.nodes if node.agent_role == "backend")

    reopened = GuidedState(tmp_path / "empy-workspace")
    projects = reopened.public()["projects"]
    assert len(projects) == 1
    assert projects[0]["id"] == first.active_project_id
    assert len(projects[0]["tasks"]) == 1
    assert reopened.active_project_id == first.active_project_id
    assert reopened.active_task_id == first_task_id
    assert reopened.task is not None
    assert reopened.plan is not None
    assert reopened.phase == "plan"

    reopened.create_plan("Add a bounded follow-up to the backend service")
    assert len(reopened.public()["active_project"]["tasks"]) == 2
    reopened.select_task(first_task_id)
    assert reopened.active_task_id == first_task_id
    assert reopened.task is not None
    assert reopened.task.title == "Update the backend service"

    archive = tmp_path / "release.zip"
    manifest = tmp_path / "release.manifest.json"
    checksum = tmp_path / "release.zip.sha256"
    archive.write_bytes(b"zip")
    manifest.write_text(
        '{"archive_mode":"delta","changed_files":["README.md"],"deleted_files":[],"extraction_root":"source"}\n',
        encoding="utf-8",
    )
    checksum.write_text("abc  release.zip\n", encoding="utf-8")
    reopened.store.create_release(
        task_id=first_task_id,
        project_id=reopened.active_project_id,
        archive_path=str(archive),
        manifest_path=str(manifest),
        checksum_path=str(checksum),
        sha256="abc",
        file_count=2,
        verified=True,
    )

    restarted = GuidedState(tmp_path / "empy-workspace")

    assert restarted.export is not None
    assert restarted.export.archive_path == archive
    assert restarted.export.verified is True
    assert restarted.export.changed_files == ("README.md",)
    assert restarted.public()["brain"]["source"] == "local_project_brain_index"


def test_guided_state_shows_only_five_newest_projects(tmp_path: Path) -> None:
    state = GuidedState(tmp_path / "empy-workspace")
    imported_ids: list[str] = []

    for index in range(6):
        source = tmp_path / f"project-{index}"
        source.mkdir()
        (source / "README.md").write_text(f"project {index}\n", encoding="utf-8")
        state.import_path(str(source))
        assert state.active_project_id is not None
        imported_ids.append(state.active_project_id)

    visible = state.public()["projects"]

    assert len(visible) == 5
    assert [item["id"] for item in visible] == list(reversed(imported_ids[-5:]))
    # The sixth record remains persisted for recovery/history; only the API
    # presentation is bounded.
    assert len(state.store.list_projects()) == 6


def test_ticket_with_inline_constraint_still_has_an_actionable_requirement(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")

    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan(
        "Review and verify the project; without changing the original files or including secrets"
    )

    assert state.phase == "plan"
    assert state.task is not None
    assert state.task.title == "Review and verify the project"


def test_reset_keeps_project_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    project_id = state.active_project_id

    state.reset()

    assert state.active_project_id is None
    assert project_id is not None
    assert state.public()["projects"][0]["id"] == project_id


def test_missing_saved_project_keeps_project_list_open(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")

    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    assert state.detection is not None
    imported_root = state.detection.descriptor.root

    shutil.rmtree(imported_root)
    reopened = GuidedState(tmp_path / "empy-workspace")
    public = reopened.public()

    assert public["active_project"] is None
    assert public["projects"][0]["available"] is False
    assert "دوباره وارد" in public["error"]


def test_browser_folder_upload_isolated_and_security_filtered(tmp_path: Path) -> None:
    state = GuidedState(tmp_path / "empy-workspace")
    upload_id = state.start_folder_upload()

    state.receive_folder_upload(
        upload_id,
        "README.md",
        io.BytesIO(b"demo\n"),
        len(b"demo\n"),
    )
    state.receive_folder_upload(
        upload_id,
        ".env",
        io.BytesIO(b"TOKEN=secret\n"),
        len(b"TOKEN=secret\n"),
    )
    state.finish_folder_upload(upload_id)

    assert state.active_project_id is not None
    assert state.detection is not None
    assert (state.detection.descriptor.root / "README.md").is_file()
    assert not (state.detection.descriptor.root / ".env").exists()
    assert upload_id not in state.upload_sessions
    public = state.public()
    assert public["message_level"] == "warning"
    assert public["import_report"] == {
        "status": "partial",
        "copied_files": 1,
        "skipped_files": 1,
        "categories": {"access_or_copy": 1},
        "verification_readiness": {
            "status": "needs_attention",
            "checks": [],
            "diagnostics": [
                (
                    "No safe verification checks were detected for this project. "
                    "Configure .empy/verification.json or add a supported test, "
                    "build, or lint entry point before export."
                ),
            ],
        },
    }

    reopened = GuidedState(tmp_path / "empy-workspace")
    assert reopened.public()["message_level"] == "warning"
    assert reopened.public()["import_report"] == public["import_report"]


def test_import_reports_missing_composer_dependency_before_ticket_planning(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "composer.json").write_text(
        '{"name":"demo/php-app","require":{"example/package":"1.0"},'
        '"scripts":{"test":"php tests/run.php"}}\n',
        encoding="utf-8",
    )
    (source / "composer.lock").write_text("{}\n", encoding="utf-8")
    (source / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))

    readiness = state.public()["import_report"]["verification_readiness"]
    assert readiness["status"] == "needs_attention"
    assert any("vendor/autoload.php" in item for item in readiness["diagnostics"])
    assert state.public()["message_level"] == "warning"
    assert "vendor/autoload.php" in state.public()["message"]


def test_export_registers_release_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Package the project")
    root = state.detection.descriptor.root
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    state.review = ReviewReport(
        schema_version=1,
        review_id="review-test",
        project_root=str(root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-test",
        project_root=str(root),
        project_type="unknown",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck(
                    check_id="package",
                    label="Package check",
                    category="build",
                    command=("empy", "package-check"),
                ),
                status="pass",
                returncode=0,
                stdout="ok\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )

    state.export_project(str(tmp_path / "release.zip"))

    assert state.export is not None
    assert state.active_task_id is not None
    releases = state.store.list_task_releases(state.active_task_id)
    assert len(releases) == 1
    assert releases[0].sha256 == state.export.sha256
    assert state.public()["active_project"]["releases"][0]["verified"] is True


def test_release_gate_explains_explicit_export_after_zero_file_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Audit the project\nDo not change files")
    root = state.detection.descriptor.root
    check = VerificationCheck(
        check_id="package",
        label="Package check",
        category="build",
        command=("empy", "package-check"),
    )
    result = VerificationResult(
        check=check,
        status="pass",
        returncode=0,
        stdout="ok\n",
        stderr="",
        started_at="now",
        finished_at="now",
    )
    state.review = ReviewReport(
        schema_version=1,
        review_id="review-zero-files",
        project_root=str(root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-zero-files",
        project_root=str(root),
        project_type="generic",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(result,),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )

    public = state.public()

    assert public["release_gate"] == {
        "status": "blocked",
        "ready": False,
        "blockers": ["No changed project files are available for a delta ZIP."],
        "exported": False,
    }


def test_release_gate_blocks_failed_verification_before_export(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Audit the project")
    root = state.detection.descriptor.root
    state.review = ReviewReport(
        schema_version=1,
        review_id="review-blocked",
        project_root=str(root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-blocked",
        project_root=str(root),
        project_type="generic",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(),
        evidence_path=str(tmp_path / "evidence"),
        diagnostics=("Site audit failed: public_html/index.html is missing.",),
    )

    public = state.public()

    assert public["release_gate"]["status"] == "blocked"
    assert public["release_gate"]["ready"] is False
    with pytest.raises(RuntimeError, match="Export is blocked"):
        state.export_project(str(tmp_path / "blocked.zip"))


def test_release_gate_blocks_file_drift_after_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    assert state.detection is not None
    root = state.detection.descriptor.root
    (root / "README.md").write_text("after review\n", encoding="utf-8")
    state.review = state.review_store.create(root)
    state.decide_all("accept")
    state.run = SimpleNamespace(status="completed")
    check = VerificationCheck(
        check_id="review-drift",
        label="Review drift check",
        category="tests",
        command=("true",),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-review-drift",
        project_root=str(root),
        project_type="generic",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=check,
                status="pass",
                returncode=0,
                stdout="ok\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )
    (root / "README.md").write_text("changed after review\n", encoding="utf-8")

    gate = state._release_gate()

    assert gate["status"] == "blocked"
    assert gate["ready"] is False
    assert any("changed after Review" in item for item in gate["blockers"])


def test_restart_does_not_restore_a_tampered_v3_release(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    assert state.detection is not None
    root = state.detection.descriptor.root
    (root / "README.md").write_text("after\n", encoding="utf-8")
    state.review = ReviewReport(
        schema_version=1,
        review_id="review-release-restore",
        project_root=str(root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-release-restore",
        project_root=str(root),
        project_type="generic",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck("release", "Release", "build", ("true",)),
                status="pass",
                returncode=0,
                stdout="ok\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )
    archive = tmp_path / "release.zip"
    state.export_project(str(archive))
    archive.write_bytes(b"tampered")

    reopened = GuidedState(tmp_path / "empy-workspace")

    assert reopened.export is None
    assert reopened.error is not None
    assert "was not restored" in reopened.error


def test_release_gate_distinguishes_pending_review_from_a_blocked_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    assert state.detection is not None
    root = state.detection.descriptor.root
    (root / "README.md").write_text("after\n", encoding="utf-8")
    state.review = state.review_store.create(root)
    state.run = SimpleNamespace(status="completed")
    verification_check = VerificationCheck(
        check_id="review-gate",
        label="Review gate check",
        category="quality",
        command=("empy", "verify"),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-review-pending",
        project_root=str(root),
        project_type="generic",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=verification_check,
                status="pass",
                returncode=0,
                stdout="ok\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )

    waiting = state._release_gate()

    assert waiting["status"] == "awaiting_review"
    assert waiting["ready"] is False
    assert waiting["blockers"] == ["1 changed file(s) still need a review decision."]

    state.decide_all("accept")
    ready = state._release_gate()

    assert ready["status"] == "ready_for_export"
    assert ready["ready"] is True
    assert ready["blockers"] == []


def test_release_gate_accepts_verified_no_change_without_delta_zip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html" / "index.html").write_text(
        "<html><body><h1>Existing homepage</h1></body></html>\n",
        encoding="utf-8",
    )
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Improve the homepage chart layout")
    assert state.graph is not None
    assert state.detection is not None
    assert state.task is not None
    root = state.detection.descriptor.root

    state.run = SimpleNamespace(
        status="completed",
        node_results=(
            SimpleNamespace(
                node_id="node-implement-frontend",
                status="completed",
                changed_files=(),
                summary=(
                    "The requested homepage state is already present. "
                    "EMPY_NODE_RESULT: PASS"
                ),
            ),
        ),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-no-change",
        project_root=str(root),
        project_type="static",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck("homepage", "Homepage", "static", ("true",)),
                status="pass",
                returncode=0,
                stdout="ok\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )
    state.review = ReviewReport(
        schema_version=1,
        review_id="review-no-change",
        project_root=str(root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )

    gate = state._release_gate()

    assert gate["status"] == "verified_no_change"
    assert gate["ready"] is False
    assert gate["blockers"] == ["No changed project files are available for a delta ZIP."]
    assert state._run_has_attested_no_change() is True


def test_restart_invalidates_old_passing_verification_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    state = GuidedState(workspace)
    state.import_path(str(source))
    state.create_plan("Audit the project")

    assert state.active_project_id is not None
    assert state.active_task_id is not None
    assert state.graph is not None
    assert state.task is not None
    assert state.detection is not None
    run = CodexGraphExecution(
        schema_version=1,
        run_id="old-run",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="completed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(),
        events=(),
        usage=None,
        schedule=(),
    )
    state.execution_store.save_run(run)
    old_verification = VerificationReport(
        schema_version=1,
        verification_id="old-verification",
        project_root=str(state.detection.descriptor.root),
        project_type="php",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(),
        evidence_path=str(workspace / "verification" / "evidence"),
        finalized_at="now",
    )
    state.verification_store.save(old_verification)
    review = ReviewReport(
        schema_version=1,
        review_id="old-review",
        project_root=str(state.detection.descriptor.root),
        base_revision="HEAD",
        created_at="now",
        updated_at="now",
        status="complete",
        files=(),
    )
    state.review_store.save(review)
    workspace_run = state.store.create_run(
        task_id=state.active_task_id,
        project_id=state.active_project_id,
        state="completed",
        summary="old run",
        driver_name="codex",
    )
    manifest = state._write_run_manifest(
        workspace_run.run_id,
        codex_run_id=run.run_id,
        verification_id=old_verification.verification_id,
        review_id=review.review_id,
    )
    state.store.update_run(
        workspace_run.run_id,
        state="completed",
        summary="old run",
        driver_name="codex",
        evidence_path=str(manifest),
    )

    reopened = GuidedState(workspace)

    assert reopened.verification is not None
    assert reopened.verification.status == "fail"
    assert any("older or different" in item for item in reopened.verification.diagnostics)
    assert reopened.run is not None
    assert reopened.run.status == "failed"
    public = reopened.public()
    assert public["release_gate"]["status"] == "blocked"
    assert public["run_report"]["guidance"]["kind"] == "stale_verification"
    assert "ادامه" in public["run_report"]["guidance"]["steps"][0]


def test_public_state_exposes_budget_brain_and_benchmark_without_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "service.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Update the service")
    state.run_benchmark()

    public = state.public()

    assert public["brain"]["file_count"] >= 2
    assert public["budget"]["estimated_context_tokens"] == state.budget.estimated_context_tokens
    assert public["plan"]["estimate_source"] == "provider_neutral_local_estimate"
    assert public["provider_usage"] is None
    assert public["benchmark"]["candidate_files"]
    assert not any(str(tmp_path) in item for item in public["benchmark"]["candidate_files"])


def test_benchmark_endpoint_requires_auth_and_valid_plan(tmp_path: Path) -> None:
    state = GuidedState(tmp_path / "workspace")
    handler = RequestHandler.__new__(RequestHandler)
    handler.server = SimpleNamespace(token="secret-token", state=state)
    handler.path = "/api/benchmark"
    handler.headers = {}

    assert handler._authorized() is False

    handler.headers = {"X-Empy-Token": "secret-token"}
    assert handler._authorized() is True
    try:
        handler._handle_post("/api/benchmark", {})
    except RuntimeError as exc:
        assert "Build a plan" in str(exc)
    else:
        raise AssertionError("benchmark without a plan succeeded")


def test_provider_is_not_inspected_when_verification_preflight_is_blocked(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    calls: list[str] = []

    class DriverStub:
        def inspect(self, *, refresh: bool = False) -> object:
            del refresh
            calls.append("inspect")
            raise AssertionError("provider inspection must not run before verification preflight")

    state.driver = DriverStub()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Verification preflight blocked"):
        state.start_run()

    assert calls == []


def test_cancel_run_requests_runtime_stop(tmp_path: Path) -> None:
    state = GuidedState(tmp_path / "workspace")
    calls: list[str] = []

    class RuntimeStub:
        def cancel(self) -> None:
            calls.append("cancel")

    state.runtime = RuntimeStub()  # type: ignore[assignment]
    state.running = True

    state.cancel_run()

    assert calls == ["cancel"]
    assert state.message == "درخواست توقف اجرا ثبت شد."
    assert state.logs[-1]["text"] == "Run cancellation requested."


def test_cancel_run_requires_active_runtime(tmp_path: Path) -> None:
    state = GuidedState(tmp_path / "workspace")

    with pytest.raises(RuntimeError, match="active run"):
        state.cancel_run()


def test_brain_index_survives_restart(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    first = GuidedState(tmp_path / "empy-workspace")
    first.import_path(str(source))
    project_id = first.active_project_id
    brain_root = first.brain_index.project_root if first.brain_index is not None else None

    reopened = GuidedState(tmp_path / "empy-workspace")

    assert project_id is not None
    assert reopened.active_project_id == project_id
    assert reopened.brain_index is not None
    assert brain_root is not None
    assert reopened.brain_index.project_root == brain_root


def test_public_exposes_safe_bilingual_execution_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")

    assert state.graph is not None
    graph_node = state.graph.nodes[0]
    workspace_evidence = state.workspace_root / "runs" / "run-1" / "events.jsonl"
    node_result = CodexNodeExecution(
        node_id=graph_node.node_id,
        task_id=f"{state.task.task_id}:{graph_node.step_id}",
        status="completed",
        started_at="2026-08-10T00:00:00+00:00",
        finished_at="2026-08-10T00:00:01.500000+00:00",
        return_code=0,
        thread_id="thread-1",
        summary="README update completed",
        changed_files=("README.md",),
        event_count=2,
        events_path=str(workspace_evidence),
        stderr_path=str(workspace_evidence.with_name("stderr.txt")),
        final_message_path=str(workspace_evidence.with_name("final.txt")),
        command_path=str(workspace_evidence.with_name("command.json")),
        usage=TokenUsage(
            input=10,
            output=5,
            cached=2,
            total=15,
            source="provider",
            provider="codex",
        ),
    )
    installation = CodexInstallation(
        availability="available",
        executable="/opt/homebrew/bin/codex",
        version="codex-cli test",
        authenticated=True,
        message="ready",
    )
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="run-1",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="completed",
        started_at="2026-08-10T00:00:00+00:00",
        finished_at="2026-08-10T00:00:01.500000+00:00",
        installation=installation,
        node_results=(node_result,),
        events=(),
        usage=node_result.usage,
        schedule=(
            CodexWaveExecution(
                wave=1,
                node_ids=(graph_node.node_id,),
                mode="serial",
                capacity=1,
                started_at="2026-08-10T00:00:00+00:00",
                finished_at="2026-08-10T00:00:01.500000+00:00",
            ),
        ),
    )

    report = state.public()["run_report"]

    assert report["usage"]["total_tokens"] == 15
    assert report["nodes"][0]["role"] == graph_node.agent_role
    assert report["nodes"][0]["duration_seconds"] == 1.5
    assert report["nodes"][0]["usage"]["source"] == "provider"
    assert report["nodes"][0]["evidence"]["events"] == "runs/run-1/events.jsonl"
    assert str(state.workspace_root) not in str(report)
    assert report["verification"]["status"] == "not_run"
    assert report["schedule"][0]["mode"] == "serial"


def test_failed_verification_is_visible_and_can_seed_a_follow_up_ticket(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    (source / "index.html").write_text("<main>demo</main>\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")

    assert state.graph is not None
    assert state.run is None
    check = VerificationCheck(
        check_id="site-audit",
        label="Site audit",
        category="tests",
        command=("php", "site-audit.php"),
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-failure",
        project_root=str(state.detection.descriptor.root),
        project_type="php",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=check,
                status="fail",
                returncode=1,
                stdout="",
                stderr=f"missing public_html/index.html in {state.detection.descriptor.root}\n",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        diagnostics=("The project entry page is missing.",),
    )

    # A minimal completed run is enough to exercise the public execution report.
    from empy_studio.drivers import CodexGraphExecution, CodexInstallation

    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="run-failure",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="completed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(),
        events=(),
        usage=None,
        schedule=(),
        error_code=None,
        error_message=None,
    )
    public = state.public()
    report = public["run_report"]
    assert report["verification"]["diagnostics"] == ["The project entry page is missing."]
    assert report["verification"]["failures"][0]["label"] == "Site audit"
    assert report["guidance"]["kind"] == "verification_failed"
    assert "ZIP" in report["guidance"]["summary"]
    assert all("Agent run" not in item for item in public["release_gate"]["blockers"])
    assert str(state.detection.descriptor.root) not in str(report)
    assert "<project>" in report["verification"]["failures"][0]["detail"]
    assert public["failure_context"]["title"] == "علت واضح توقف کار"
    assert public["failure_context"]["repair_available"] is True
    assert public["failure_context"]["failures"][0]["user_finding"]
    assert "public_html/index.html" in public["failure_context"]["suggested_ticket"]
    assert "قرارداد تست" in public["failure_context"]["failures"][0]["action"]

    state.resume_ticket()
    assert state.phase == "task"
    assert state.continuation_context is not None
    assert "Site audit" in state.continuation_context
    follow_up = state.public()["failure_context"]
    assert follow_up is not None
    assert any("public_html/index.html" in item for item in follow_up["findings"])
    assert "public_html/index.html" in follow_up["suggested_ticket"]
    state.create_plan("Update index.html to address the reported project entry page issue")
    assert state.task is not None
    assert "Previous Empy verification findings" in "\n".join(state.task.constraints)
    assert "Previous Empy verification findings" not in state.task.objective

    reopened = GuidedState(tmp_path / "workspace")
    # Starting a new corrective plan consumes the old failure banner; the
    # findings remain in the new task constraints and are not rendered a
    # second time on the plan screen.
    assert reopened.public()["failure_context"] is None


def test_token_budget_failure_is_classified_as_a_retryable_execution_problem() -> None:
    assert _failure_kind(
        "Codex exceeded Empy's fresh-token limit of 35758 tokens; the node was stopped before it could pass."
    ) == "token_budget"


def test_dirty_worktree_failure_has_a_bilingual_recovery_path(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")

    assert state.graph is not None
    assert state.task is not None
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="dirty-run",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="failed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(),
        events=(),
        usage=None,
        schedule=(),
        error_code="dirty_worktree",
        error_message=(
            "Codex execution requires a clean Git worktree so Empy can audit file ownership. "
            "Commit or restore these paths first: README.md"
        ),
    )

    fa = state.public()["failure_context"]
    assert fa is not None
    assert fa["kind"] == "dirty_worktree"
    assert fa["title"] == "تلاش قبلی نیاز به ادامهٔ امن دارد"
    assert fa["repair_available"] is True
    assert "فایل اصلی" in fa["summary"]
    assert state.public()["run_report"]["guidance"]["action"] == "auto-repair"

    state.language = "en"
    en = state.public()["failure_context"]
    assert en is not None
    assert en["kind"] == "dirty_worktree"
    assert en["title"] == "The previous attempt needs a safe retry"
    assert "original project is unchanged" in en["summary"]


def test_failed_agent_report_is_recovered_as_a_specific_ownership_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the project UI")

    assert state.graph is not None
    assert state.task is not None
    assert state.detection is not None
    node = state.graph.nodes[0]
    final_message = state.workspace_root / "runs" / "failed" / "final-message.md"
    final_message.parent.mkdir(parents=True)
    final_message.write_text(
        "فایل مالکیت‌داده‌شده در فهرست فایل‌های مجاز این نود نیست؛ "
        "public_html/index.html در پروژه وجود ندارد. EMPY_NODE_RESULT: FAIL\n",
        encoding="utf-8",
    )
    node_result = CodexNodeExecution(
        node_id=node.node_id,
        task_id=f"{state.task.task_id}:{node.step_id}",
        status="failed",
        started_at="now",
        finished_at="now",
        return_code=1,
        thread_id="thread-failed",
        summary="The implementation Agent completed its process but produced no project change.",
        changed_files=(),
        event_count=1,
        events_path=str(final_message.with_name("events.jsonl")),
        stderr_path=str(final_message.with_name("stderr.txt")),
        final_message_path=str(final_message),
        command_path=str(final_message.with_name("command.json")),
        error_code="objective_not_met",
        error_message="The implementation Agent completed its process but produced no project change.",
    )
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="failed-ownership-run",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="failed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(node_result,),
        events=(),
        usage=None,
        schedule=(),
        error_code="objective_not_met",
        error_message=(
            "The implementation Agent completed its process but produced no project change "
            "and did not provide a PASS attestation."
        ),
    )
    state.failure_context = {
        "kind": "no_change",
        "diagnostics": ["old generic context"],
        "failures": [
            {
                "label": "Agent execution",
                "kind": "no_change",
                "detail": "old generic context",
            },
        ],
    }

    context = state.public()["failure_context"]

    assert context is not None
    assert context["kind"] == "ownership_mismatch"
    assert context["failures"][0]["kind"] == "ownership_mismatch"
    assert "ساختار واقعی پروژه" in context["failures"][0]["user_finding"]
    assert "Agent report" in context["failures"][0]["detail"]
    assert "public_html/index.html" in context["findings"][0]
    assert state.public()["run_report"]["guidance"]["kind"] == "ownership_mismatch"
    continuation = state._build_continuation_context()
    assert "فایل مالکیت" in continuation
    assert "public_html/index.html" in continuation


def test_runtime_failure_has_an_automatic_continuation_hook(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    calls: list[str] = []

    def fake_auto_repair(*, automatic: bool = False) -> None:
        calls.append("auto-repair")

    state.auto_repair = fake_auto_repair  # type: ignore[method-assign]
    state._maybe_start_automatic_repair(reason="runtime failure")

    assert calls == ["auto-repair"]


def test_planning_failure_stays_on_ticket_screen_with_recovery_action(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))

    def fail_materialization(task: object) -> None:
        raise ValueError(
            "approved implementation plan has no writable files for writing roles (backend)"
        )

    state._materialize_workflow = fail_materialization  # type: ignore[method-assign]
    with pytest.raises(ValueError):
        state.create_plan("Update the backend entrypoint")

    public = state.public()
    assert public["phase"] == "task"
    assert public["failure_context"]["kind"] == "no_writable_files"
    assert public["failure_context"]["repair_available"] is True
    assert "فایل قابل‌ویرایش" in public["failure_context"]["title"]
    assert "تغییر نکرده" in public["error"]


def test_retry_carries_partial_work_and_restores_cumulative_review_diff(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")

    assert state.detection is not None
    isolated_root = state.detection.descriptor.root
    (isolated_root / "README.md").write_text("unfinished attempt\n", encoding="utf-8")

    recovered = state._prepare_clean_worktree_for_run()

    assert recovered == ("README.md",)
    assert (isolated_root / "README.md").read_text(encoding="utf-8") == "unfinished attempt\n"
    assert state.carry_forward_base_revision is not None
    assert not subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=isolated_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    state._restore_carry_forward_review_base(isolated_root)
    dirty = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=isolated_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "README.md" in dirty
    assert state.carry_forward_base_revision is None
    assert (source / "README.md").read_text(encoding="utf-8") == "before\n"


def test_token_budget_run_has_clear_guidance_and_no_false_verification_failure(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")

    assert state.graph is not None
    assert state.task is not None
    assert state.detection is not None
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="run-budget",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="failed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(),
        events=(),
        usage=None,
        schedule=(),
        error_code="budget_exceeded",
        error_message=(
            "Codex exceeded Empy's fresh-token limit of 35758 tokens; "
            "the node was stopped before it could pass."
        ),
    )

    public = state.public()

    assert public["run_report"]["guidance"]["kind"] == "token_budget"
    assert public["run_report"]["guidance"]["action"] == "auto-repair"
    assert public["failure_context"]["kind"] == "token_budget"
    assert "ZIP" in public["failure_context"]["summary"]

    state.start_run = lambda: None  # type: ignore[method-assign]
    state.auto_repair()

    assert state.compact_retry is True
    assert state.task is not None
    assert state.task.objective == "Update the README"
    assert "fresh-token limit" in "\n".join(state.task.constraints)


def test_token_budget_retry_uses_a_smaller_context_policy(tmp_path: Path) -> None:
    """A compact retry must never send a larger pack than the first pass."""

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("project notes\n" * 5000, encoding="utf-8")
    (source / "architecture.md").write_text("architecture\n" * 5000, encoding="utf-8")
    (source / "legacy.txt").write_text("legacy\n" * 5000, encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Review the project and report its structure")

    assert state.task is not None
    state.compact_retry = True
    _plan, compact_context, _budget, _graph = state._materialize_workflow(state.task)

    assert all(len(pack.files) <= 3 for pack in compact_context.packs)
    assert all(pack.total_bytes <= 12_288 for pack in compact_context.packs)
    assert all(item.included_bytes <= 4_096 for pack in compact_context.packs for item in pack.files)


def test_budget_limited_scoped_change_is_kept_for_local_verification(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README.md")

    assert state.graph is not None
    assert state.task is not None
    writer = next(node for node in state.graph.nodes if node.agent_role == "backend")
    node_results = []
    for node in state.graph.nodes:
        if node.node_id == writer.node_id:
            node_results.append(
                CodexNodeExecution(
                    node_id=node.node_id,
                    task_id=f"{state.task.task_id}:{node.step_id}",
                    status="failed",
                    started_at="now",
                    finished_at="now",
                    return_code=0,
                    thread_id="thread-budget",
                    summary="The requested file was changed.",
                    changed_files=("README.md",),
                    event_count=1,
                    events_path="events.jsonl",
                    stderr_path="stderr.log",
                    final_message_path="final.md",
                    command_path="command.json",
                    error_code="budget_exceeded",
                    error_message="fresh-token limit exceeded",
                )
            )
        else:
            node_results.append(
                CodexNodeExecution(
                    node_id=node.node_id,
                    task_id=f"{state.task.task_id}:{node.step_id}",
                    status="skipped",
                    started_at="now",
                    finished_at="now",
                    return_code=None,
                    thread_id=None,
                    summary="Skipped after upstream budget warning.",
                    changed_files=(),
                    event_count=0,
                    events_path="events.jsonl",
                    stderr_path="stderr.log",
                    final_message_path="final.md",
                    command_path="command.json",
                )
            )
    result = CodexGraphExecution(
        schema_version=1,
        run_id="budget-with-change",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=state.graph.project_root,
        provider="codex",
        status="failed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=tuple(node_results),
        events=(),
        error_code="budget_exceeded",
        error_message="fresh-token limit exceeded",
    )

    assert state._budget_result_can_continue_to_verification(result) is True
    promoted = state._promote_verified_budget_result(result)
    assert promoted.status == "completed"
    assert promoted.error_code is None
    assert all(node.status == "completed" for node in promoted.node_results)

    no_change = replace(
        result,
        node_results=(replace(result.node_results[0], changed_files=()), *result.node_results[1:]),
    )
    assert state._budget_result_can_continue_to_verification(no_change) is False


def test_failure_context_identifies_entrypoint_contract_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html" / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (source / "public_html" / "index.php").write_text(
        "<?php echo 'ok';\n",
        encoding="utf-8",
    )
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Verify the homepage")
    assert state.detection is not None
    root = state.detection.descriptor.root
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-contract-mismatch",
        project_root=str(root),
        project_type="php",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck(
                    check_id="site-audit",
                    label="Site audit",
                    category="tests",
                    command=("composer", "run-script", "test"),
                ),
                status="fail",
                returncode=1,
                stdout="missing public_html/index.html\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
    )

    context = state.public()["failure_context"]

    assert context is not None
    assert context["failures"][0]["kind"] == "verification_contract_mismatch"
    assert context["failures"][0]["user_finding"] == (
        "صفحهٔ اول ساخته نشد: تست دنبال «public_html/index.html» است، "
        "اما فایل واقعی پروژه «public_html/index.php» است."
    )
    assert context["repair_available"] is True
    assert "detected application entry point is index.php" in context["failures"][0]["detail"]
    assert "قرارداد Verification" in context["failures"][0]["action"]


def test_unrelated_verification_failure_does_not_retry_changed_ticket(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "public_html" / "assets").mkdir(parents=True)
    (source / "public_html" / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (source / "public_html" / "index.php").write_text(
        "<?php echo 'ok';\n",
        encoding="utf-8",
    )
    (source / "public_html" / "assets" / "home-v1.19.css").write_text(
        ".chart { display: block; }\n",
        encoding="utf-8",
    )

    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Turn the bank pie chart into a 3D chart")
    assert state.detection is not None
    root = state.detection.descriptor.root
    (root / "public_html" / "assets" / "home-v1.19.css").write_text(
        ".chart { transform: perspective(800px) rotateX(12deg); }\n",
        encoding="utf-8",
    )
    state.review = state.review_store.create(root)
    assert state.review.files

    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-unrelated-contract",
        project_root=str(root),
        project_type="php",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck(
                    check_id="site-audit",
                    label="Site audit",
                    category="tests",
                    command=("composer", "run-script", "test"),
                ),
                status="fail",
                returncode=1,
                stdout="missing public_html/index.html\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
        diagnostics=("The project entry page is missing.",),
    )
    assert state.graph is not None
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="run-unrelated-contract",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(root),
        provider="codex",
        status="completed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(),
        events=(),
        usage=None,
        schedule=(),
        error_code=None,
        error_message=None,
    )
    state._capture_failure_context()

    public = state.public()
    context = public["failure_context"]
    assert context is not None
    assert context["scope"] == "project"
    assert "مستقل" in context["title"]
    assert context["repair_available"] is False
    assert public["run_report"]["guidance"]["kind"] == "verification_project"
    assert public["run_report"]["guidance"]["repair_available"] is False

    calls: list[str] = []
    state.auto_repair = lambda **_: calls.append("auto-repair")  # type: ignore[method-assign]
    state._maybe_start_automatic_repair(reason="Verification found a real issue")
    assert calls == []
    assert state.recovery.status == "ready"


def test_auto_repair_creates_real_follow_up_plan_once(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html" / "composer.json").write_text(
        '{"name":"demo/site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (source / "public_html" / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    (source / "public_html" / "tests").mkdir()
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("صفحه ایندکس و لینک دکمه ها را اصلاح کن")
    assert state.detection is not None
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-contract-mismatch",
        project_root=str(state.detection.descriptor.root),
        project_type="php",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=VerificationCheck(
                    check_id="site-audit",
                    label="Site audit",
                    category="tests",
                    command=("php", "tests/site-audit.php"),
                ),
                status="fail",
                returncode=1,
                stdout="missing public_html/index.html\n",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path=str(tmp_path / "evidence"),
    )
    state.start_run = lambda: None  # type: ignore[method-assign]

    state.auto_repair()

    assert state.repair_attempts == 1
    assert state.task is not None
    assert "علت قطعی شکست قبلی" not in state.task.objective
    assert "علت قطعی شکست قبلی" in "\n".join(state.task.constraints)
    assert state.plan is not None
    assert [step.suggested_agent for step in state.plan.steps] == ["frontend"]
    with pytest.raises(RuntimeError, match="already active"):
        state.auto_repair()


def test_recovery_skips_failed_discovery_and_assigns_writer_owner(
    tmp_path: Path,
) -> None:
    """A failed read-only Discovery node must not consume another cycle."""

    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html" / "composer.json").write_text(
        '{"name":"demo/site"}\n',
        encoding="utf-8",
    )
    (source / "public_html" / "index.php").write_text(
        "<?php echo 'ok';\n",
        encoding="utf-8",
    )
    (source / "public_html" / "assets").mkdir()
    (source / "public_html" / "assets" / "app.js").write_text(
        "document.body.dataset.chart = 'ready';\n",
        encoding="utf-8",
    )
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("بررسی کن نمودار")

    assert state.graph is not None
    assert state.task is not None
    assert state.detection is not None
    discovery = next(node for node in state.graph.nodes if node.agent_role == "discovery")
    failed = CodexNodeExecution(
        node_id=discovery.node_id,
        task_id=f"{state.task.task_id}:{discovery.step_id}",
        status="failed",
        started_at="now",
        finished_at="now",
        return_code=1,
        thread_id="discovery-failed",
        summary="Discovery could not identify the implementation scope. EMPY_NODE_RESULT: FAIL",
        changed_files=(),
        event_count=1,
        events_path="events.jsonl",
        stderr_path="stderr.log",
        final_message_path="final.md",
        command_path="command.json",
        error_code="objective_not_met",
        error_message="Discovery did not identify the implementation scope.",
    )
    state.run = CodexGraphExecution(
        schema_version=1,
        run_id="discovery-failed-run",
        graph_id=state.graph.graph_id,
        task_id=state.task.task_id,
        project_root=str(state.detection.descriptor.root),
        provider="codex",
        status="failed",
        started_at="now",
        finished_at="now",
        installation=CodexInstallation(
            availability="available",
            executable="codex",
            version="test",
            authenticated=True,
            message="ready",
        ),
        node_results=(failed,),
        events=(),
        usage=None,
        schedule=(),
        error_code="objective_not_met",
        error_message="Discovery did not identify the implementation scope.",
    )
    state.start_run = lambda: None  # type: ignore[method-assign]

    state.auto_repair()

    assert state.recovery.history[-1]["owner"] == "frontend"
    assert state.plan is not None
    assert all(step.suggested_agent != "discovery" for step in state.plan.steps)
    assert state.plan.steps[0].suggested_agent == "frontend"


def test_diagnostic_only_failure_has_required_action(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "composer.json").write_text("{\"scripts\": {\"test\": \"php tests.php\"}}\n", encoding="utf-8")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Audit dependencies")
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-diagnostic-only",
        project_root=str(state.detection.descriptor.root),
        project_type="php",
        status="fail",
        started_at="now",
        finished_at="now",
        results=(),
        evidence_path=str(tmp_path / "evidence"),
        diagnostics=(
            "Composer test/release scripts were not executed because vendor/autoload.php is missing.",
        ),
    )
    context = state.public()["failure_context"]
    assert context is not None
    assert context["failures"][0]["label"] == "Verification configuration"
    assert "وابستگی" in context["failures"][0]["action"]
    assert "vendor/autoload.php" in context["suggested_ticket"]


def test_verified_export_has_authenticated_download_endpoint(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    archive = workspace / "releases" / "demo-release.zip"
    archive.parent.mkdir(parents=True)
    payload = b"verified zip payload"
    archive.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = archive.with_suffix(".manifest.json")
    manifest.write_text(
        '{"archive_mode":"delta","changed_files":["README.md"]}\n',
        encoding="utf-8",
    )
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")

    server = create_server(workspace=workspace, token="download-token", port=0)
    server.state.export = ExportedProject(
        project_root=workspace / "project",
        archive_path=archive,
        manifest_path=manifest,
        checksum_path=checksum,
        sha256=digest,
        file_count=1,
        verified=True,
        changed_files=("README.md",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(f"{base_url}/api/export/download", timeout=2)
        assert unauthorized.value.code == 403

        request = urllib.request.Request(
            f"{base_url}/api/export/download?token=download-token"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert response.read() == payload
            assert response.headers["Content-Type"] == "application/zip"
            assert response.headers["Content-Disposition"].startswith("attachment;")

        manifest_request = urllib.request.Request(
            f"{base_url}/api/export/manifest?token=download-token"
        )
        with urllib.request.urlopen(manifest_request, timeout=2) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("application/json")
            assert b"README.md" in response.read()

        checksum_request = urllib.request.Request(
            f"{base_url}/api/export/checksum?token=download-token"
        )
        with urllib.request.urlopen(checksum_request, timeout=2) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/plain")
            assert digest.encode("ascii") in response.read()

        archive.write_bytes(b"tampered")
        with pytest.raises(urllib.error.HTTPError) as tampered:
            urllib.request.urlopen(request, timeout=2)
        assert tampered.value.code == 409
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _memory_ready_state(tmp_path: Path) -> GuidedState:
    source = tmp_path / "memory-source"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'memory-demo'\n",
        encoding="utf-8",
    )
    (source / "README.md").write_text("before\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    state = GuidedState(tmp_path / "memory-workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    return state


def _record_memory_failure(state: GuidedState) -> None:
    state.error = (
        "The Agent produced no project change and did not provide a PASS attestation."
    )
    state._capture_failure_context()


def test_failure_memory_blocks_exact_unchanged_provider_run_and_survives_restart(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    _record_memory_failure(state)
    records = state.store.list_failures(state.active_project_id, include_resolved=False)
    assert len(records) == 1
    assert records[0].kind == "no_change"
    assert records[0].affected_paths == ("README.md",)
    assert records[0].evidence[0].startswith("scope_target:")

    restarted = GuidedState(tmp_path / "memory-workspace")
    restarted.new_ticket()
    restarted.create_plan("Update the README")
    calls: list[str] = []

    class DriverStub:
        def inspect(self, *, refresh: bool = False) -> CodexInstallation:
            del refresh
            calls.append("inspect")
            raise AssertionError("an unchanged failure must stop before provider inspection")

    restarted.driver = DriverStub()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="همان علت شکست|same confirmed failure"):
        restarted.start_run()

    assert calls == []
    memory = {
        "blocked": restarted.failure_memory_blocked,
        "open_count": restarted.failure_memory_open_count,
        "records": [record.compact_summary() for record in restarted.failure_memory_matches],
    }
    assert memory["blocked"] is True
    assert memory["open_count"] == 1
    assert memory["records"][0]["kind"] == "no_change"
    assert "scope_snapshot" not in json.dumps(memory, ensure_ascii=False)


def test_failure_memory_allows_changed_snapshot_and_calls_provider_once(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    _record_memory_failure(state)
    assert state.detection is not None
    (state.detection.descriptor.root / "README.md").write_text(
        "corrective change\n",
        encoding="utf-8",
    )
    state._refresh_failure_memory_view()
    assert state.failure_memory_blocked is False

    calls: list[str] = []

    class DriverStub:
        def inspect(self, *, refresh: bool = False) -> CodexInstallation:
            del refresh
            calls.append("inspect")
            return CodexInstallation(
                availability="available",
                executable="codex",
                version="test",
                authenticated=True,
                message="ready",
            )

    state.driver = DriverStub()  # type: ignore[assignment]
    state._run_worker = lambda workspace_run_id: None  # type: ignore[method-assign]
    state.start_run()
    state._cancel_recovery_deadline()
    state.running = False
    assert calls == ["inspect"]


def test_failure_memory_does_not_add_unrelated_project_hint_to_new_ticket(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    _record_memory_failure(state)

    state.new_ticket()
    state.create_plan("Update tests/test_smoke.py")

    assert state.failure_memory_blocked is False
    assert state.failure_memory_hint == ""
    assert state.task is not None
    assert "Known project failure memory" not in "\n".join(state.task.constraints)


def test_failure_memory_blocks_repeated_timeout_before_provider_inspection(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    state.error = "Verification timed out while checking the project."
    state._capture_failure_context()
    state.new_ticket()
    state.create_plan("Update the README")
    calls: list[str] = []

    class DriverStub:
        def inspect(self, *, refresh: bool = False) -> CodexInstallation:
            del refresh
            calls.append("inspect")
            raise AssertionError("a repeated timeout must be stopped locally")

    state.driver = DriverStub()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="همان علت شکست|same confirmed failure"):
        state.start_run()
    assert calls == []


def test_failure_memory_keeps_multiple_verified_findings_separate(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    checks = tuple(
        VerificationCheck(
            check_id=f"check-{index}",
            label=f"Check {index}",
            category="tests",
            command=("pytest", "-q"),
        )
        for index in (1, 2)
    )
    state.verification = VerificationReport(
        schema_version=1,
        verification_id="verification-two-findings",
        project_root=str(state.detection.descriptor.root),
        project_type="python",
        status="fail",
        started_at="now",
        finished_at="now",
        results=tuple(
            VerificationResult(
                check=check,
                status="fail",
                returncode=1,
                stdout="",
                stderr=f"failure-{index}",
                started_at="now",
                finished_at="now",
            )
            for index, check in enumerate(checks, start=1)
        ),
        evidence_path="evidence/two-findings",
    )

    state._capture_failure_context()
    records = state.store.list_failures(state.active_project_id, include_resolved=False)

    assert len(records) == 2
    assert {record.summary for record in records} == {"failure-1", "failure-2"}


def test_failure_memory_resolves_only_after_final_verification(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    _record_memory_failure(state)
    record = state.store.list_failures(state.active_project_id, include_resolved=False)[0]
    check = VerificationCheck(
        check_id="smoke",
        label="Smoke test",
        category="tests",
        command=("pytest", "-q"),
    )
    verification = VerificationReport(
        schema_version=1,
        verification_id="verification-memory-pass",
        project_root=str(state.detection.descriptor.root),
        project_type="python",
        status="pass",
        started_at="now",
        finished_at="now",
        results=(
            VerificationResult(
                check=check,
                status="pass",
                returncode=0,
                stdout="1 passed",
                stderr="",
                started_at="now",
                finished_at="now",
            ),
        ),
        evidence_path="evidence/verification-memory-pass",
    )
    assert verification.finalize_allowed is True

    state._resolve_failure_memory_after_verification(verification)
    assert state.store.get_failure(record.memory_id).status == "resolved"
    assert state.store.list_failures(state.active_project_id, include_resolved=False) == ()


def test_failure_memory_is_project_scoped_and_malformed_rows_fail_closed(
    tmp_path: Path,
) -> None:
    state = _memory_ready_state(tmp_path)
    _record_memory_failure(state)
    first_project_id = state.active_project_id
    assert first_project_id is not None

    second_source = tmp_path / "second-source"
    second_source.mkdir()
    (second_source / "pyproject.toml").write_text(
        "[project]\nname = 'other-demo'\n",
        encoding="utf-8",
    )
    (second_source / "README.md").write_text("other\n", encoding="utf-8")
    (second_source / "tests").mkdir()
    (second_source / "tests" / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    state.import_path(str(second_source))
    assert state.active_project_id != first_project_id
    assert state.public()["failure_memory"]["open_count"] == 0

    connection = sqlite3.connect(state.store.database_path)
    try:
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
                "malformed-memory-row",
                state.active_project_id,
                None,
                "a" * 64,
                "check_failed",
                "malformed row",
                "inspect",
                "[]",
                "not-json",
                "open",
                1,
                "[]",
                "now",
                "now",
                None,
                "[]",
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    state._refresh_failure_memory_view()
    assert state.failure_memory_blocked is False
    assert state.failure_memory_open_count == 0
    assert state.public()["failure_memory"]["records"] == []
