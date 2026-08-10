from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from empy_studio.drivers import (
    CodexGraphExecution,
    CodexInstallation,
    CodexNodeExecution,
    CodexWaveExecution,
)
from empy_studio.review_workspace import ReviewReport
from empy_studio.token_usage import TokenUsage
from empy_studio.verification_pipeline import VerificationCheck, VerificationReport, VerificationResult
from empy_studio.web_desktop import GuidedState, RequestHandler


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
        results=(),
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
        error_code="process_failed",
        error_message="verification failed",
    )
    public = state.public()
    report = public["run_report"]
    assert report["verification"]["diagnostics"] == ["The project entry page is missing."]
    assert report["verification"]["failures"][0]["label"] == "Site audit"
    assert str(state.detection.descriptor.root) not in str(report)
    assert "<project>" in report["verification"]["failures"][0]["detail"]

    state.resume_ticket()
    assert state.phase == "task"
    assert state.continuation_context is not None
    assert "Site audit" in state.continuation_context
    state.create_plan("Update index.html to address the reported project entry page issue")
    assert state.task is not None
    assert "Previous Empy verification findings" in state.task.objective
