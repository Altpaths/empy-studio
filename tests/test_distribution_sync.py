from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from empy_studio.distribution_manifest import (
    DistributionAsset,
    DistributionManifest,
)
from empy_studio.distribution_sync import (
    DistributionAssetMismatch,
    DistributionLinkMap,
    DistributionReleaseNotFound,
    build_distribution_link_map,
    resolve_remote_release,
    sync_distribution_links,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


class FakeTransport:
    def __init__(
        self,
        responses: dict[
            str,
            dict[str, Any]
            | list[dict[str, Any]],
        ],
    ) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def request_json(
        self,
        url: str,
        *,
        token: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        self.calls.append(url)
        return self.responses[url]


def asset(
    target: str,
    name: str,
    digest: str,
    size: int,
) -> DistributionAsset:
    return DistributionAsset.create(
        target=target,
        asset_name=name,
        sha256=digest,
        size_bytes=size,
        media_type="text/plain",
    )


def manifest() -> DistributionManifest:
    return DistributionManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0"
        ),
        repository="Altpaths/empy-studio",
        minimum_python="3.10",
        assets=(
            asset(
                "macos-arm64",
                "install-macos-arm64.sh",
                "a" * 64,
                100,
            ),
            asset(
                "windows-x86_64",
                "install-windows-x86_64.ps1",
                "b" * 64,
                200,
            ),
        ),
    )


def remote_release(
    *,
    tag: str = "v1.0.0",
    prerelease: bool = False,
) -> dict[str, Any]:
    return {
        "id": 501,
        "tag_name": tag,
        "name": "Empy Studio 1.0.0",
        "html_url": (
            "https://github.com/Altpaths/"
            "empy-studio/releases/tag/v1.0.0"
        ),
        "draft": False,
        "prerelease": prerelease,
        "published_at": (
            "2026-08-03T12:00:00Z"
        ),
        "assets": [
            {
                "id": 1,
                "name": (
                    "install-macos-arm64.sh"
                ),
                "size": 100,
                "state": "uploaded",
                "content_type": "text/plain",
                "browser_download_url": (
                    "https://github.com/download/"
                    "install-macos-arm64.sh"
                ),
                "download_count": 12,
                "digest": "sha256:" + "a" * 64,
            },
            {
                "id": 2,
                "name": (
                    "install-windows-x86_64.ps1"
                ),
                "size": 200,
                "state": "uploaded",
                "content_type": "text/plain",
                "browser_download_url": (
                    "https://github.com/download/"
                    "install-windows-x86_64.ps1"
                ),
                "download_count": 8,
                "digest": "sha256:" + "b" * 64,
            },
        ],
    }


def test_resolves_latest_stable_release() -> None:
    url = (
        "https://api.github.com/repos/"
        "Altpaths/empy-studio/releases/latest"
    )
    transport = FakeTransport(
        {url: remote_release()}
    )

    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-stable",
        transport=transport,
    )

    assert release.tag == "v1.0.0"
    assert release.prerelease is False


def test_resolves_release_by_tag() -> None:
    url = (
        "https://api.github.com/repos/"
        "Altpaths/empy-studio/releases/"
        "tags/v1.0.0"
    )
    transport = FakeTransport(
        {url: remote_release()}
    )

    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="tag",
        tag="v1.0.0",
        transport=transport,
    )

    assert release.release_id == 501


def test_resolves_latest_prerelease() -> None:
    url = (
        "https://api.github.com/repos/"
        "Altpaths/empy-studio/releases"
        "?per_page=100"
    )
    older = remote_release(
        tag="v1.0.0-rc.1",
        prerelease=True,
    )
    older["id"] = 400
    older["published_at"] = (
        "2026-08-01T12:00:00Z"
    )

    newer = remote_release(
        tag="v1.0.0-rc.2",
        prerelease=True,
    )
    newer["id"] = 401
    newer["published_at"] = (
        "2026-08-02T12:00:00Z"
    )

    transport = FakeTransport(
        {url: [older, newer]}
    )

    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-prerelease",
        transport=transport,
    )

    assert release.tag == "v1.0.0-rc.2"


def test_rejects_missing_prerelease() -> None:
    url = (
        "https://api.github.com/repos/"
        "Altpaths/empy-studio/releases"
        "?per_page=100"
    )
    transport = FakeTransport(
        {url: [remote_release()]}
    )

    with pytest.raises(
        DistributionReleaseNotFound,
        match="prerelease",
    ):
        resolve_remote_release(
            repository="Altpaths/empy-studio",
            selection="latest-prerelease",
            transport=transport,
        )


def test_builds_direct_download_link_map() -> None:
    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-stable",
        transport=FakeTransport(
            {
                (
                    "https://api.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/latest"
                ): remote_release()
            }
        ),
    )

    link_map = build_distribution_link_map(
        manifest(),
        release,
    )

    mac = link_map.download_for_target(
        "macos-arm64"
    )
    assert mac.url.endswith(
        "install-macos-arm64.sh"
    )
    assert mac.download_count == 12


def test_syncs_manifest_to_release() -> None:
    url = (
        "https://api.github.com/repos/"
        "Altpaths/empy-studio/releases/latest"
    )
    link_map = sync_distribution_links(
        manifest(),
        selection="latest-stable",
        transport=FakeTransport(
            {url: remote_release()}
        ),
    )

    assert link_map.release_tag == "v1.0.0"
    assert len(link_map.downloads) == 2


def test_rejects_release_tag_mismatch() -> None:
    release_data = remote_release(
        tag="v2.0.0"
    )
    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="tag",
        tag="v2.0.0",
        transport=FakeTransport(
            {
                (
                    "https://api.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/tags/v2.0.0"
                ): release_data
            }
        ),
    )

    with pytest.raises(
        DistributionAssetMismatch,
        match="tag",
    ):
        build_distribution_link_map(
            manifest(),
            release,
        )


def test_rejects_missing_asset() -> None:
    release_data = remote_release()
    release_data["assets"] = (
        release_data["assets"][:1]
    )
    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-stable",
        transport=FakeTransport(
            {
                (
                    "https://api.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/latest"
                ): release_data
            }
        ),
    )

    with pytest.raises(
        DistributionAssetMismatch,
        match="missing",
    ):
        build_distribution_link_map(
            manifest(),
            release,
        )


def test_rejects_remote_size_mismatch() -> None:
    release_data = remote_release()
    release_data["assets"][0]["size"] = 999
    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-stable",
        transport=FakeTransport(
            {
                (
                    "https://api.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/latest"
                ): release_data
            }
        ),
    )

    with pytest.raises(
        DistributionAssetMismatch,
        match="size mismatch",
    ):
        build_distribution_link_map(
            manifest(),
            release,
        )


def test_link_map_round_trip(
    tmp_path: Path,
) -> None:
    release = resolve_remote_release(
        repository="Altpaths/empy-studio",
        selection="latest-stable",
        transport=FakeTransport(
            {
                (
                    "https://api.github.com/"
                    "repos/Altpaths/empy-studio/"
                    "releases/latest"
                ): remote_release()
            }
        ),
    )
    link_map = build_distribution_link_map(
        manifest(),
        release,
    )

    path = link_map.save(
        tmp_path / "distribution-links.json"
    )

    assert DistributionLinkMap.load(path) == link_map
