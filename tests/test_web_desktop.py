from __future__ import annotations

import hashlib
import io
import threading
import urllib.error
import urllib.request
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
from empy_studio.web_desktop import GuidedState, RequestHandler, create_server


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
    manifest.write_text("{}\n", encoding="utf-8")
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
    assert restarted.public()["brain"]["source"] == "local_project_brain_index"


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
    }

    reopened = GuidedState(tmp_path / "empy-workspace")
    assert reopened.public()["message_level"] == "warning"
    assert reopened.public()["import_report"] == public["import_report"]


def test_export_registers_release_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("demo\n", encoding="utf-8")
    state = GuidedState(tmp_path / "empy-workspace")
    state.import_path(str(source))
    state.create_plan("Package the project")
    root = state.detection.descriptor.root
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
        "status": "ready_for_export",
        "ready": True,
        "blockers": [],
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
    assert public["failure_context"]["title"] == "علت دقیق توقف اجرای قبلی"
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
    assert "Previous Empy verification findings" in state.task.objective

    reopened = GuidedState(tmp_path / "workspace")
    assert reopened.public()["failure_context"] is not None
    assert "public_html/index.html" in reopened.public()["failure_context"]["suggested_ticket"]


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

    server = create_server(workspace=workspace, token="download-token", port=0)
    server.state.export = ExportedProject(
        project_root=workspace / "project",
        archive_path=archive,
        manifest_path=archive.with_suffix(".manifest.json"),
        checksum_path=archive.with_suffix(".zip.sha256"),
        sha256=digest,
        file_count=1,
        verified=True,
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

        archive.write_bytes(b"tampered")
        with pytest.raises(urllib.error.HTTPError) as tampered:
            urllib.request.urlopen(request, timeout=2)
        assert tampered.value.code == 409
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
