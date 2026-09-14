from pathlib import Path

import pytest

from empy_studio.core.recovery import RecoveryPolicy, RecoveryState, external_block
from empy_studio.web_desktop import GuidedState


def test_recovery_limits_unknown_usage_and_round_trip() -> None:
    state = RecoveryState(policy=RecoveryPolicy(max_fresh_tokens=10000), original_request="Fix links")
    state.account("one", 2000)
    state.account("one", 2000)
    state.account("two", None, 3000)
    assert state.known_fresh_tokens == 2000
    assert not state.usage_complete
    assert state.limit_reason(planned_tokens=6000).startswith("budget_exhausted")
    assert RecoveryState.from_dict(state.to_dict()) == state
    state.started_at = 0
    assert state.limit_reason(now=1801).startswith("time_exhausted")
    state.attempts = 3
    assert state.limit_reason(now=0).startswith("attempts_exhausted")
    assert state.limit_reason(now=0, planned_tokens=6000, check_attempts=False).startswith("budget_exhausted")


def test_recovery_no_progress_and_external_blockers() -> None:
    state = RecoveryState()
    assert state.record_failure("test A failed in 2s", "one", "frontend") is None
    state.begin()
    assert state.record_failure("test B failed", "two", "frontend") is None
    state.begin()
    assert state.record_failure("test B failed", "three", "frontend").startswith("no_progress")
    assert state.history[-1]["strategy"] == "inspect_contract_and_root_cause"
    assert external_block("authentication required").startswith("credentials")
    assert external_block("The selected free/local model or Responses endpoint is unsupported by the local gateway.").startswith("provider")
    assert external_block("Dependency preparation blocked").startswith("environment")
    with pytest.raises(ValueError):
        RecoveryPolicy(max_attempts=11)


def test_recovery_restores_interrupted_without_replay_and_edits_same_ticket(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update the README")
    task_id = state.active_task_id
    state.create_plan("Update the README introduction", task_id=task_id)
    assert state.active_task_id == task_id
    assert len(state.public()["tasks"]) == 1
    state.recovery.begin()
    state._save_recovery()
    restored = GuidedState(tmp_path / "workspace")
    assert restored.recovery.status == "stopped"
    assert restored.recovery.stop_reason.startswith("interrupted")
    assert restored.recovery.attempts == 1
    assert not restored.running
    restored.new_ticket()
    assert restored.active_project_id == state.active_project_id
    assert restored.active_task_id is None
    assert restored.phase == "task"


def test_budget_is_always_economy_even_for_older_clients(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README", budget_preset="economy")
    economy = state.budget.total_limit_tokens
    task_id = state.active_task_id
    state.create_plan("Update README", task_id=task_id, budget_preset="extended")
    assert state.budget.total_limit_tokens == economy
    assert state.active_task_id == task_id
    # Simulate a pre-upgrade installation with both an extended setting and contract.
    state.store.set_setting(f"budget-preset.v1.{state.active_project_id}", "extended")
    contract = state.store.get_task(task_id).contract
    contract["budget"]["preset"] = "extended"
    state.store.update_task(task_id, contract=contract)
    restored = GuidedState(tmp_path / "workspace")
    assert restored.budget.preset == "economy"
    assert restored.budget.total_limit_tokens == economy
    state.create_plan("Update README", budget_preset="unbounded")
    assert state.budget.preset == "economy"


def test_switching_tickets_preserves_recovery_limits(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README")
    first = state.active_task_id
    state.recovery.begin()
    state.recovery.account("first-run", 1234)
    state.recovery.stop("no_progress")
    state._save_recovery()
    state.new_ticket()
    state.create_plan("Update README again", budget_preset="extended")
    state.select_task(first)
    assert state.budget.preset == "economy"
    assert state.recovery.attempts == 1
    assert state.recovery.known_fresh_tokens == 1234
    assert state.recovery.stop_reason == "no_progress"


def test_individual_file_acceptance_does_not_move_head_before_last_decision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in ("README.md", "NOTES.md"):
        (source / name).write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README.md and NOTES.md")
    root = state.detection.descriptor.root
    for name in ("README.md", "NOTES.md"):
        (root / name).write_text("after")
    state.review = state.review_store.create(root)
    state.decide_all("accept", relative_path="README.md")
    assert state.review.pending_count == 1
    state.decide_all("accept", relative_path="NOTES.md")
    assert state.review.pending_count == 0
    assert state.review.accepted_count == 2


def test_explicit_html_ticket_has_one_scoped_frontend_owner(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html/index.html").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update public_html/index.html to contain a homepage. Preserve all other files.")
    writers = [node for node in state.graph.nodes if node.agent_role == "frontend"]
    assert len(writers) == 1
    assert writers[0].owned_files == ("public_html/index.html",)


def test_scope_violation_never_enters_repair_checkpoint(tmp_path: Path) -> None:
    from types import SimpleNamespace

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README")
    state.run = SimpleNamespace(error_code="scope_violation", status="failed")
    def forbidden_checkpoint():
        pytest.fail("Unowned changes must not be checkpointed for repair")
    state._prepare_clean_worktree_for_run = forbidden_checkpoint
    with pytest.raises(RuntimeError, match="scope_violation"):
        state.auto_repair()
    assert state.recovery.attempts == 0
    assert state.recovery.status == "stopped"


def test_reverting_one_file_rechecks_actual_remaining_tree(tmp_path: Path) -> None:
    import shutil

    from empy_studio.verification_pipeline import VerificationRuntime

    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("Node/npm required for actual verification")
    source = tmp_path / "source"
    (source / "public_html").mkdir(parents=True)
    (source / "public_html/index.html").write_text("before")
    (source / "README.md").write_text("before")
    (source / "package.json").write_text('{"name":"review-test","scripts":{"test":"node verify.mjs"}}')
    (source / "verify.mjs").write_text("import fs from 'node:fs'; process.exit(fs.readFileSync('public_html/index.html','utf8').includes('fixed') ? 0 : 1);")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update public_html/index.html")
    root = state.detection.descriptor.root
    (root / "public_html/index.html").write_text("fixed")
    (root / "README.md").write_text("after")
    state.review = state.review_store.create(root)
    state.verification = VerificationRuntime().run(detection=state.detection, evidence_root=state.verification_store.evidence_root)
    assert state.verification.finalize_allowed
    previous_id = state.verification.verification_id
    state.decide_all("revert", relative_path="public_html/index.html")
    assert state.verification.verification_id != previous_id
    assert not state.verification.finalize_allowed
    state.decide_all("accept", relative_path="README.md")
    assert not state._release_gate()["ready"]
    assert (root / "public_html/index.html").read_text() == "before"


def test_start_page_keeps_history_without_restoring_or_scanning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("before")
    state = GuidedState(tmp_path / "workspace")
    state.import_path(str(source))
    state.create_plan("Update README")
    project_id = state.active_project_id
    task_id = state.active_task_id

    def unexpected_restore(*args, **kwargs):
        raise AssertionError("Start page must not restore or rescan a project")

    monkeypatch.setattr(GuidedState, "select_project", unexpected_restore)
    reopened = GuidedState(tmp_path / "workspace", restore_session=False)
    assert reopened.phase == "project"
    assert reopened.active_project_id is None
    assert reopened.active_task_id is None
    assert reopened.run is None
    assert reopened.verification is None
    assert reopened.store.get_task(task_id).project_id == project_id
    assert len(reopened.public()["projects"]) == 1
