from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.core import (
    AgentPatch,
    AgentRunGraph,
    AgentRunNode,
    FileOwnership,
    apply_sync_report,
    build_sync_report,
    content_sha256,
    default_agent_registry,
    resolve_sync_conflict,
)


def _graph(root: Path, *, two_writers: bool = False) -> AgentRunGraph:
    frontend = AgentRunNode(
        node_id="node-frontend",
        step_id="step-frontend",
        title="Frontend",
        objective="Update frontend",
        agent_id="frontend-agent",
        agent_role="frontend",
        required_capabilities=("read-context", "modify-frontend", "bounded-execution"),
        matched_capabilities=("read-context", "modify-frontend", "bounded-execution"),
        context_pack_id="pack-front",
        token_allocation_step_id="step-frontend",
        token_limit=1000,
        depends_on=(),
        wave=1,
        sequence=1,
        owned_files=("resources/views/home.blade.php",),
        read_only_files=(),
    )
    nodes = [frontend]
    ownership = [
        FileOwnership(
            relative_path="resources/views/home.blade.php",
            owner_node_id="node-frontend",
            owner_agent_id="frontend-agent",
            owner_step_id="step-frontend",
            reader_agent_ids=(),
            reason="frontend ownership",
        )
    ]
    waves = [("node-frontend",)]
    if two_writers:
        backend = AgentRunNode(
            node_id="node-backend",
            step_id="step-backend",
            title="Backend",
            objective="Update backend",
            agent_id="backend-agent",
            agent_role="backend",
            required_capabilities=("read-context", "modify-backend", "bounded-execution"),
            matched_capabilities=("read-context", "modify-backend", "bounded-execution"),
            context_pack_id="pack-back",
            token_allocation_step_id="step-backend",
            token_limit=1000,
            depends_on=("node-frontend",),
            wave=2,
            sequence=2,
            owned_files=("app/service.py",),
            read_only_files=(),
        )
        nodes.append(backend)
        ownership.append(
            FileOwnership(
                relative_path="app/service.py",
                owner_node_id="node-backend",
                owner_agent_id="backend-agent",
                owner_step_id="step-backend",
                reader_agent_ids=(),
                reason="backend ownership",
            )
        )
        waves.append(("node-backend",))
    graph = AgentRunGraph(
        schema_version=1,
        graph_id="graph-sync",
        plan_id="plan-sync",
        selection_id="selection-sync",
        budget_id="budget-sync",
        task_id="task-sync",
        project_root=str(root),
        created_at="2026-08-04T00:00:00+00:00",
        status="ready",
        registry=default_agent_registry(),
        nodes=tuple(nodes),
        ownership=tuple(ownership),
        waves=tuple(waves),
        protected_exclusions=(".env",),
    )
    graph.validate()
    return graph


def _patch(path: str, base: str | None, content: str | None, **kwargs: object) -> AgentPatch:
    return AgentPatch(
        patch_id=str(kwargs.get("patch_id", "patch-1")),
        node_id=str(kwargs.get("node_id", "node-frontend")),
        agent_id=str(kwargs.get("agent_id", "frontend-agent")),
        step_id=str(kwargs.get("step_id", "step-frontend")),
        relative_path=path,
        operation=kwargs.get("operation", "modify"),  # type: ignore[arg-type]
        base_sha256=base,
        content=content,
        created_at="2026-08-04T00:00:00+00:00",
        sequence=int(kwargs.get("sequence", 0)),
    )


def test_clean_owned_patch_is_ready_and_applies(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "new\n"),),
    )

    assert report.status == "ready"
    assert not report.conflicts
    final = apply_sync_report(report)
    assert target.read_text(encoding="utf-8") == "new\n"
    assert final.status == "applied"
    assert final.applied_patch_ids == ("patch-1",)


def test_patch_queue_follows_agent_sequence_not_input_order(tmp_path: Path) -> None:
    front = tmp_path / "resources/views/home.blade.php"
    back = tmp_path / "app/service.py"
    front.parent.mkdir(parents=True)
    back.parent.mkdir(parents=True)
    front.write_text("front\n")
    back.write_text("back\n")
    report = build_sync_report(
        graph=_graph(tmp_path, two_writers=True),
        patches=(
            _patch("app/service.py", content_sha256("back\n"), "back2\n", patch_id="p2", node_id="node-backend", agent_id="backend-agent", step_id="step-backend"),
            _patch("resources/views/home.blade.php", content_sha256("front\n"), "front2\n", patch_id="p1"),
        ),
    )
    assert tuple(item.patch.patch_id for item in report.queue) == ("p1", "p2")


def test_ownership_violation_blocks_sync(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("old\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "bad\n", node_id="node-missing"),),
    )
    assert report.status == "blocked"
    assert "ownership-violation" in {item.kind for item in report.conflicts}
    with pytest.raises(ValueError, match="unresolved conflicts"):
        apply_sync_report(report)


def test_protected_file_is_never_applied_without_user_resolution(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("SECRET=old\n")
    patch = _patch(".env", content_sha256("SECRET=old\n"), "SECRET=new\n")
    report = build_sync_report(graph=_graph(tmp_path), patches=(patch,))
    assert "protected-file" in {item.kind for item in report.conflicts}
    assert target.read_text() == "SECRET=old\n"


def test_stale_base_requires_decision_and_keep_current_skips(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("current\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "agent\n"),),
    )
    stale = next(item for item in report.conflicts if item.kind == "stale-base")
    resolved = report
    for conflict in report.conflicts:
        resolved = resolve_sync_conflict(resolved, conflict_id=conflict.conflict_id, choice="keep-current")
    final = apply_sync_report(resolved)
    assert stale.resolved is False
    assert target.read_text() == "current\n"
    assert final.skipped_patch_ids == ("patch-1",)


def test_apply_patch_resolution_can_override_stale_base(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("current\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "agent\n"),),
    )
    for conflict in report.conflicts:
        report = resolve_sync_conflict(report, conflict_id=conflict.conflict_id, choice="apply-patch")
    final = apply_sync_report(report)
    assert target.read_text() == "agent\n"
    assert final.status == "applied"


def test_manual_content_resolution_writes_user_content(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("current\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "agent\n"),),
    )
    for conflict in report.conflicts:
        report = resolve_sync_conflict(report, conflict_id=conflict.conflict_id, choice="manual-content", manual_content="merged\n")
    apply_sync_report(report)
    assert target.read_text() == "merged\n"


def test_duplicate_writes_are_detected_and_not_lost(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("old\n")
    base = content_sha256("old\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(
            _patch("resources/views/home.blade.php", base, "one\n", patch_id="p1", sequence=1),
            _patch("resources/views/home.blade.php", base, "two\n", patch_id="p2", sequence=2),
        ),
    )
    duplicate = [item for item in report.conflicts if item.kind == "duplicate-write"]
    assert len(duplicate) == 2
    assert {item.patch_id for item in duplicate} == {"p1", "p2"}
    assert {item.patch.patch_id for item in report.queue} == {"p1", "p2"}


def test_create_and_delete_operations(tmp_path: Path) -> None:
    existing = tmp_path / "resources/views/home.blade.php"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n")
    graph = _graph(tmp_path)
    delete_report = build_sync_report(
        graph=graph,
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), None, operation="delete"),),
    )
    apply_sync_report(delete_report)
    assert not existing.exists()

    create_report = build_sync_report(
        graph=graph,
        patches=(_patch("resources/views/home.blade.php", None, "new\n", operation="create", patch_id="create"),),
    )
    apply_sync_report(create_report)
    assert existing.read_text() == "new\n"


def test_invalid_operation_and_unsafe_path_are_rejected(tmp_path: Path) -> None:
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", None, "new\n", operation="modify"),),
    )
    assert "invalid-operation" in {item.kind for item in report.conflicts}
    with pytest.raises(ValueError, match="unsafe patch path"):
        build_sync_report(graph=_graph(tmp_path), patches=(_patch("../escape", None, "bad", operation="create"),))


def test_workspace_change_after_review_aborts_before_write(tmp_path: Path) -> None:
    target = tmp_path / "resources/views/home.blade.php"
    target.parent.mkdir(parents=True)
    target.write_text("old\n")
    report = build_sync_report(
        graph=_graph(tmp_path),
        patches=(_patch("resources/views/home.blade.php", content_sha256("old\n"), "new\n"),),
    )
    target.write_text("external\n")
    with pytest.raises(ValueError, match="workspace changed before apply"):
        apply_sync_report(report)
    assert target.read_text() == "external\n"
