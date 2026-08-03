from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from empy_studio.artifact_index import (
    build_artifact_index,
)
from empy_studio.release_guard import (
    ReleaseGuardError,
    ReleaseRollbackError,
    guard_release,
    rollback_failed_release,
)
from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


class FakeTransport:
    def __init__(
        self,
        *,
        conclusion: str = "success",
    ) -> None:
        self.conclusion = conclusion
        self.calls: list[tuple[str, str]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        self.calls.append((method, url))

        if "/actions/runs" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 501,
                        "name": "CI",
                        "head_sha": "abc123",
                        "conclusion": self.conclusion,
                        "run_started_at": (
                            "2026-08-03T10:00:00Z"
                        ),
                    }
                ]
            }

        if method == "DELETE":
            return {}

        raise AssertionError((method, url))


def manifest() -> ReleaseManifest:
    return ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse("1.0.0"),
        release_name="Empy Studio 1.0.0",
        notes_file="RELEASE_NOTES.md",
        previous_version=ReleaseVersion.parse("0.9.0"),
    )


def artifact_index(tmp_path: Path):
    root = tmp_path / "dist"
    root.mkdir()
    artifact = root / "release.zip"
    artifact.write_bytes(b"release")
    return build_artifact_index(
        manifest(),
        root,
        [artifact],
    )


def patch_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    branch: str = "main",
    clean: bool = True,
    tag_commit: str = "abc123",
) -> None:
    def fake_git(
        repository_root: Path,
        *args: str,
    ) -> str:
        if args == ("branch", "--show-current"):
            return branch
        if args == ("status", "--porcelain"):
            return "" if clean else " M file.py"
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == (
            "rev-list",
            "-n",
            "1",
            "v1.0.0",
        ):
            return tag_commit
        raise AssertionError(args)

    monkeypatch.setattr(
        "empy_studio.release_guard._run_git",
        fake_git,
    )


def test_guard_accepts_successful_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(monkeypatch)

    result = guard_release(
        manifest(),
        artifact_index(tmp_path),
        repository_root=tmp_path,
        repository="Altpaths/empy-studio",
        token="token",
        transport=FakeTransport(),
    )

    assert result.status == "ready"
    assert result.workflow_conclusion == "success"
    assert "ci_success" in result.checks


def test_guard_rejects_failed_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(monkeypatch)

    with pytest.raises(
        ReleaseGuardError,
        match="did not succeed",
    ):
        guard_release(
            manifest(),
            artifact_index(tmp_path),
            repository_root=tmp_path,
            repository="Altpaths/empy-studio",
            token="token",
            transport=FakeTransport(
                conclusion="failure"
            ),
        )


def test_guard_rejects_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(
        monkeypatch,
        clean=False,
    )

    with pytest.raises(
        ReleaseGuardError,
        match="clean Git working tree",
    ):
        guard_release(
            manifest(),
            artifact_index(tmp_path),
            repository_root=tmp_path,
            repository="Altpaths/empy-studio",
            token="token",
            transport=FakeTransport(),
        )


def test_guard_rejects_wrong_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(
        monkeypatch,
        branch="feature/release-manager",
    )

    with pytest.raises(
        ReleaseGuardError,
        match="current branch",
    ):
        guard_release(
            manifest(),
            artifact_index(tmp_path),
            repository_root=tmp_path,
            repository="Altpaths/empy-studio",
            token="token",
            transport=FakeTransport(),
        )


def test_guard_rejects_tag_not_at_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(
        monkeypatch,
        tag_commit="different",
    )

    with pytest.raises(
        ReleaseGuardError,
        match="does not point to HEAD",
    ):
        guard_release(
            manifest(),
            artifact_index(tmp_path),
            repository_root=tmp_path,
            repository="Altpaths/empy-studio",
            token="token",
            transport=FakeTransport(),
        )


def test_rollback_deletes_release_and_tag(
    tmp_path: Path,
) -> None:
    index = artifact_index(tmp_path)
    transport = FakeTransport()

    metadata = rollback_failed_release(
        transport,
        api_url="https://api.github.com",
        repository="Altpaths/empy-studio",
        token="token",
        release_id=901,
        manifest=manifest(),
        commit_sha="abc123",
        reason="upload verification failed",
        artifact_index=index,
    )

    assert metadata.deleted_release is True
    assert metadata.deleted_tag is True
    assert metadata.previous_tag == "v0.9.0"
    assert metadata.artifact_names == (
        "release.zip",
    )
    assert len(
        [
            call
            for call in transport.calls
            if call[0] == "DELETE"
        ]
    ) == 2


def test_rollback_metadata_round_trip_file(
    tmp_path: Path,
) -> None:
    metadata = rollback_failed_release(
        FakeTransport(),
        api_url="https://api.github.com",
        repository="Altpaths/empy-studio",
        token="token",
        release_id=901,
        manifest=manifest(),
        commit_sha="abc123",
        reason="failed",
        artifact_index=artifact_index(tmp_path),
    )

    path = metadata.save(
        tmp_path / "rollback.json"
    )

    assert path.is_file()
    assert '"previous_tag": "v0.9.0"' in (
        path.read_text(encoding="utf-8")
    )


def test_rollback_error_type_exists() -> None:
    assert issubclass(
        ReleaseRollbackError,
        RuntimeError,
    )
