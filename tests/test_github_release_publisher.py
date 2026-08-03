from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from empy_studio.artifact_index import (
    build_artifact_index,
)
from empy_studio.github_release_publisher import (
    GitHubConflictError,
    GitHubReleaseError,
    GitHubRepository,
    publish_github_release,
    token_from_environment,
)
from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[
            tuple[str, str, dict[str, Any] | None]
        ] = []
        self.uploads: list[
            tuple[str, str, bytes]
        ] = []
        self.assets: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        self.requests.append(
            (method, url, body)
        )

        if method == "POST":
            return {
                "id": 101,
                "upload_url": (
                    "https://uploads.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/101/assets{?name,label}"
                ),
                "html_url": (
                    "https://github.com/Altpaths/"
                    "empy-studio/releases/tag/v1.0.0"
                ),
                "draft": bool(body["draft"]),
                "prerelease": bool(
                    body["prerelease"]
                ),
            }

        if method == "GET":
            return self.assets

        raise AssertionError(method)

    def upload_asset(
        self,
        url: str,
        *,
        token: str,
        path: Path,
        media_type: str,
    ) -> dict[str, Any]:
        payload = path.read_bytes()
        self.uploads.append(
            (url, media_type, payload)
        )
        entry = {
            "id": len(self.assets) + 1,
            "name": path.name,
            "size": len(payload),
            "content_type": media_type,
            "browser_download_url": (
                "https://github.com/download/"
                + path.name
            ),
            "state": "uploaded",
        }
        self.assets.append(entry)
        return entry


def release_manifest(
    version: str = "1.0.0",
) -> ReleaseManifest:
    parsed = ReleaseVersion.parse(version)
    return ReleaseManifest.create(
        product="Empy Studio",
        version=parsed,
        release_name=f"Empy Studio {parsed}",
        notes_file="RELEASE_NOTES.md",
    )


def release_files(
    tmp_path: Path,
    manifest: ReleaseManifest,
) -> tuple[Path, Any]:
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    archive = release_dir / (
        f"empy-studio-{manifest.version}.zip"
    )
    archive.write_bytes(b"archive")

    notes = release_dir / "RELEASE_NOTES.md"
    notes.write_text(
        "# Release notes\n",
        encoding="utf-8",
    )

    index = build_artifact_index(
        manifest,
        release_dir,
        [archive],
    )
    return notes, index


def test_parses_repository_slug() -> None:
    repository = GitHubRepository.parse(
        "Altpaths/empy-studio"
    )

    assert repository.owner == "Altpaths"
    assert repository.name == "empy-studio"


def test_creates_release_and_uploads_assets(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    notes, index = release_files(
        tmp_path,
        manifest,
    )
    transport = FakeTransport()

    result = publish_github_release(
        manifest,
        index,
        repository="Altpaths/empy-studio",
        token="token",
        release_notes_path=notes,
        transport=transport,
    )

    assert result.release_id == 101
    assert result.tag == "v1.0.0"
    assert result.make_latest == "true"
    assert len(result.assets) == 1
    assert len(transport.uploads) == 1

    create_body = transport.requests[0][2]
    assert create_body is not None
    assert create_body["tag_name"] == "v1.0.0"
    assert create_body["make_latest"] == "true"


def test_prerelease_is_not_latest_by_default(
    tmp_path: Path,
) -> None:
    manifest = release_manifest(
        "1.0.0-rc.1"
    )
    notes, index = release_files(
        tmp_path,
        manifest,
    )
    transport = FakeTransport()

    result = publish_github_release(
        manifest,
        index,
        repository="Altpaths/empy-studio",
        token="token",
        release_notes_path=notes,
        transport=transport,
    )

    assert result.prerelease is True
    assert result.make_latest == "false"


def test_latest_strategy_can_be_overridden(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    notes, index = release_files(
        tmp_path,
        manifest,
    )

    result = publish_github_release(
        manifest,
        index,
        repository="Altpaths/empy-studio",
        token="token",
        release_notes_path=notes,
        latest_strategy="legacy",
        transport=FakeTransport(),
    )

    assert result.make_latest == "legacy"


def test_upload_url_contains_encoded_name(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    artifact = release_dir / "asset name.zip"
    artifact.write_bytes(b"archive")
    notes = release_dir / "RELEASE_NOTES.md"
    notes.write_text(
        "notes",
        encoding="utf-8",
    )
    index = build_artifact_index(
        manifest,
        release_dir,
        [artifact],
    )
    transport = FakeTransport()

    publish_github_release(
        manifest,
        index,
        repository="Altpaths/empy-studio",
        token="token",
        release_notes_path=notes,
        transport=transport,
    )

    assert "asset+name.zip" in (
        transport.uploads[0][0]
    )


def test_rejects_tampered_local_asset(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    notes, index = release_files(
        tmp_path,
        manifest,
    )
    artifact = (
        Path(index.artifact_root)
        / index.entries[0].relative_path
    )
    artifact.write_bytes(b"tampered")

    with pytest.raises(
        ValueError,
        match="verification failed",
    ):
        publish_github_release(
            manifest,
            index,
            repository="Altpaths/empy-studio",
            token="token",
            release_notes_path=notes,
            transport=FakeTransport(),
        )


def test_rejects_remote_size_mismatch(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    notes, index = release_files(
        tmp_path,
        manifest,
    )

    class MismatchTransport(FakeTransport):
        def request_json(
            self,
            method: str,
            url: str,
            *,
            token: str,
            body: dict[str, Any] | None = None,
        ) -> dict[str, Any] | list[dict[str, Any]]:
            result = super().request_json(
                method,
                url,
                token=token,
                body=body,
            )
            if method == "GET":
                result[0]["size"] += 1
            return result

    with pytest.raises(
        GitHubReleaseError,
        match="size mismatch",
    ):
        publish_github_release(
            manifest,
            index,
            repository="Altpaths/empy-studio",
            token="token",
            release_notes_path=notes,
            transport=MismatchTransport(),
        )


def test_rejects_empty_token(
    tmp_path: Path,
) -> None:
    manifest = release_manifest()
    notes, index = release_files(
        tmp_path,
        manifest,
    )

    with pytest.raises(
        ValueError,
        match="token",
    ):
        publish_github_release(
            manifest,
            index,
            repository="Altpaths/empy-studio",
            token=" ",
            release_notes_path=notes,
            transport=FakeTransport(),
        )


def test_reads_token_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "secret",
    )

    assert token_from_environment() == "secret"


def test_missing_environment_token_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "GITHUB_TOKEN",
        raising=False,
    )

    with pytest.raises(
        RuntimeError,
        match="GITHUB_TOKEN",
    ):
        token_from_environment()


def test_conflict_error_is_distinct() -> None:
    assert issubclass(
        GitHubConflictError,
        GitHubReleaseError,
    )
