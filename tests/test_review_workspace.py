from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from empy_studio.review_workspace import ReviewRuntime, ReviewWorkspaceAdapter


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Empy Tests")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    (root / "delete.txt").write_text("remove me\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "baseline")
    return root


def test_capture_produces_readable_changed_file_diffs(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "tracked.txt").write_text("after\n", encoding="utf-8")
    (root / "added.txt").write_text("new line\n", encoding="utf-8")
    (root / "delete.txt").unlink()

    report = ReviewRuntime().capture(root)

    assert report.status == "pending"
    assert tuple(item.relative_path for item in report.files) == (
        "added.txt",
        "delete.txt",
        "tracked.txt",
    )
    tracked = next(item for item in report.files if item.relative_path == "tracked.txt")
    added = next(item for item in report.files if item.relative_path == "added.txt")
    assert "-before" in tracked.diff_text
    assert "+after" in tracked.diff_text
    assert "--- /dev/null" in added.diff_text
    assert "+new line" in added.diff_text


def test_accept_keeps_change_and_records_explicit_decision(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "tracked.txt").write_text("accepted\n", encoding="utf-8")
    runtime = ReviewRuntime()
    report = runtime.capture(root)
    revision_before = _git(root, "rev-parse", "HEAD")

    accepted = runtime.accept(report, "tracked.txt")

    assert (root / "tracked.txt").read_text(encoding="utf-8") == "accepted\n"
    assert accepted.files[0].decision == "accepted"
    assert accepted.status == "complete"
    assert _git(root, "rev-parse", "HEAD") == revision_before


def test_revert_restores_tracked_file_without_commit(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    runtime = ReviewRuntime()
    report = runtime.capture(root)
    revision_before = _git(root, "rev-parse", "HEAD")

    reverted = runtime.revert(report, "tracked.txt")

    assert (root / "tracked.txt").read_text(encoding="utf-8") == "before\n"
    assert reverted.files[0].decision == "reverted"
    assert reverted.status == "complete"
    assert _git(root, "rev-parse", "HEAD") == revision_before


def test_revert_removes_untracked_file_safely(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    added = root / "added.txt"
    added.write_text("temporary\n", encoding="utf-8")
    runtime = ReviewRuntime()
    report = runtime.capture(root)

    reverted = runtime.revert(report, "added.txt")

    assert not added.exists()
    assert reverted.files[0].decision == "reverted"
    assert _git(root, "status", "--porcelain") == ""


def test_decision_is_blocked_when_workspace_changed_after_capture(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    target = root / "tracked.txt"
    target.write_text("first change\n", encoding="utf-8")
    runtime = ReviewRuntime()
    report = runtime.capture(root)
    target.write_text("second change\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Refresh Review Workspace"):
        runtime.accept(report, "tracked.txt")


def test_workspace_adapter_persists_accept_and_revert_decisions(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (root / "added.txt").write_text("new\n", encoding="utf-8")
    store = ReviewWorkspaceAdapter(tmp_path / "workspace")
    report = store.create(root)

    report = store.accept(report.review_id, "tracked.txt")
    report = store.revert(report.review_id, "added.txt")
    loaded = store.load(report.review_id)

    assert loaded.status == "complete"
    decisions = {item.relative_path: item.decision for item in loaded.files}
    assert decisions == {"added.txt": "reverted", "tracked.txt": "accepted"}
    assert (root / "tracked.txt").read_text(encoding="utf-8") == "changed\n"
    assert not (root / "added.txt").exists()


def test_clean_repository_creates_complete_empty_review(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    report = ReviewRuntime().capture(root)

    assert report.status == "complete"
    assert report.files == ()
    assert report.pending_count == 0


def test_revert_restores_staged_rename_safely(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "mv", "tracked.txt", "renamed.txt")
    runtime = ReviewRuntime()
    report = runtime.capture(root)

    renamed = next(item for item in report.files if item.change_kind == "renamed")
    assert renamed.relative_path == "renamed.txt"
    assert renamed.original_path == "tracked.txt"

    reverted = runtime.revert(report, "renamed.txt")

    assert (root / "tracked.txt").read_text(encoding="utf-8") == "before\n"
    assert not (root / "renamed.txt").exists()
    assert reverted.status == "complete"
    assert _git(root, "status", "--porcelain") == ""


def test_decision_is_blocked_when_head_changes_after_capture(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    target = root / "tracked.txt"
    target.write_text("reviewed change\n", encoding="utf-8")
    runtime = ReviewRuntime()
    report = runtime.capture(root)
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "external commit")

    with pytest.raises(RuntimeError, match="HEAD changed"):
        runtime.accept(report, "tracked.txt")


def test_revert_restores_deleted_tracked_file(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    target = root / "delete.txt"
    target.unlink()
    runtime = ReviewRuntime()
    report = runtime.capture(root)

    reverted = runtime.revert(report, "delete.txt")

    assert target.read_text(encoding="utf-8") == "remove me\n"
    assert reverted.status == "complete"
    assert _git(root, "status", "--porcelain") == ""


def test_binary_untracked_change_has_readable_marker(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "image.bin").write_bytes(b"\x00\x01\x02")

    report = ReviewRuntime().capture(root)

    binary = next(item for item in report.files if item.relative_path == "image.bin")
    assert binary.is_binary is True
    assert binary.diff_text == "Binary file added: image.bin\n"


def test_revert_removes_staged_added_file(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    target = root / "staged.txt"
    target.write_text("staged addition\n", encoding="utf-8")
    _git(root, "add", "staged.txt")
    runtime = ReviewRuntime()
    report = runtime.capture(root)

    reverted = runtime.revert(report, "staged.txt")

    assert not target.exists()
    assert reverted.status == "complete"
    assert _git(root, "status", "--porcelain") == ""


def test_revert_rename_is_blocked_if_source_path_reappears(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "mv", "tracked.txt", "renamed.txt")
    runtime = ReviewRuntime()
    report = runtime.capture(root)
    (root / "tracked.txt").write_text("unrelated replacement\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="source reappeared"):
        runtime.revert(report, "renamed.txt")

    assert (root / "tracked.txt").read_text(encoding="utf-8") == "unrelated replacement\n"
    assert (root / "renamed.txt").read_text(encoding="utf-8") == "before\n"
