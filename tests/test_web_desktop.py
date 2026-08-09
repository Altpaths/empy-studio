from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from empy_studio.review_workspace import ReviewReport
from empy_studio.verification_pipeline import VerificationReport
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
