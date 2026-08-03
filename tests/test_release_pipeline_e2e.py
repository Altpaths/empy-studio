from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from empy_studio.artifact_index import (
    build_artifact_index,
)
from empy_studio.release_guard import (
    ReleaseRollbackError,
)
from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_pipeline import (
    publish_release_pipeline,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


class FakeTransport:
    def __init__(
        self,
        *,
        fail_upload: bool = False,
    ) -> None:
        self.fail_upload = fail_upload
        self.assets: list[dict[str, Any]] = []
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
                        "id": 500,
                        "name": "CI",
                        "head_sha": "abc123",
                        "conclusion": "success",
                        "run_started_at": (
                            "2026-08-03T10:00:00Z"
                        ),
                    }
                ]
            }

        if method == "POST" and url.endswith(
            "/releases"
        ):
            return {
                "id": 900,
                "upload_url": (
                    "https://uploads.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/900/assets{?name,label}"
                ),
                "html_url": (
                    "https://github.com/Altpaths/"
                    "empy-studio/releases/tag/v1.0.0"
                ),
                "draft": False,
                "prerelease": False,
            }

        if method == "GET" and "/assets" in url:
            return self.assets

        if method == "DELETE":
            return {}

        raise AssertionError((method, url))

    def upload_asset(
        self,
        url: str,
        *,
        token: str,
        path: Path,
        media_type: str,
    ) -> dict[str, Any]:
        if self.fail_upload:
            raise RuntimeError("upload failed")

        data = path.read_bytes()
        asset = {
            "id": len(self.assets) + 1,
            "name": path.name,
            "size": len(data),
            "content_type": media_type,
            "browser_download_url": (
                "https://github.com/download/"
                + path.name
            ),
            "state": "uploaded",
        }
        self.assets.append(asset)
        return asset


def release_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    artifact = release_dir / "release.zip"
    artifact.write_bytes(b"release")

    notes = release_dir / "RELEASE_NOTES.md"
    notes.write_text(
        "# Release notes\n",
        encoding="utf-8",
    )

    manifest = ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0"
        ),
        release_name="Empy Studio 1.0.0",
        notes_file=str(notes),
        previous_version=ReleaseVersion.parse(
            "0.9.0"
        ),
    )
    index = build_artifact_index(
        manifest,
        release_dir,
        [artifact],
    )

    manifest_path = manifest.save(
        release_dir / "release-manifest.json"
    )
    index_path = index.save(
        release_dir / "artifacts.json"
    )
    return manifest_path, index_path, notes


def patch_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(
        repository_root: Path,
        *args: str,
    ) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == (
            "rev-list",
            "-n",
            "1",
            "v1.0.0",
        ):
            return "abc123"
        raise AssertionError(args)

    monkeypatch.setattr(
        "empy_studio.release_guard._run_git",
        fake_git,
    )


def test_complete_publish_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(monkeypatch)
    manifest_path, index_path, notes = (
        release_inputs(tmp_path)
    )

    result = publish_release_pipeline(
        manifest_path=manifest_path,
        artifact_index_path=index_path,
        release_notes_path=notes,
        repository_root=tmp_path,
        repository="Altpaths/empy-studio",
        token="token",
        transport=FakeTransport(),
        rollback_dir=tmp_path / "records",
    )

    assert result.status == "published"
    assert result.guard.workflow_conclusion == "success"
    assert result.publication.release_id == 900
    assert (
        tmp_path
        / "records"
        / "publication-v1.0.0.json"
    ).is_file()


def test_partial_publication_is_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_git(monkeypatch)
    manifest_path, index_path, notes = (
        release_inputs(tmp_path)
    )
    transport = FakeTransport(
        fail_upload=True
    )

    with pytest.raises(
        ReleaseRollbackError,
        match="rolled back",
    ):
        publish_release_pipeline(
            manifest_path=manifest_path,
            artifact_index_path=index_path,
            release_notes_path=notes,
            repository_root=tmp_path,
            repository="Altpaths/empy-studio",
            token="token",
            transport=transport,
            rollback_dir=tmp_path / "records",
        )

    assert (
        tmp_path
        / "records"
        / "rollback-v1.0.0.json"
    ).is_file()
    assert len(
        [
            call
            for call in transport.calls
            if call[0] == "DELETE"
        ]
    ) == 2
