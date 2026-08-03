from __future__ import annotations

from pathlib import Path
from typing import Any

from empy_studio.distribution_builder import (
    DistributionBuildConfig,
    build_distribution,
)
from empy_studio.distribution_manifest import (
    DistributionManifest,
)
from empy_studio.distribution_sync import (
    sync_distribution_links,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


class FakeTransport:
    def __init__(
        self,
        response: dict[str, Any],
    ) -> None:
        self.response = response

    def request_json(
        self,
        url: str,
        *,
        token: str | None = None,
    ) -> dict[str, Any]:
        return self.response


def test_distribution_build_to_link_map(
    tmp_path: Path,
) -> None:
    result = build_distribution(
        DistributionBuildConfig(
            product="Empy Studio",
            version=ReleaseVersion.parse(
                "1.0.0"
            ),
            repository=(
                "Altpaths/empy-studio"
            ),
            minimum_python="3.10",
            package_url=(
                "https://github.com/"
                "Altpaths/empy-studio/"
                "releases/download/v1.0.0/"
                "empy_studio-1.0.0-"
                "py3-none-any.whl"
            ),
            package_sha256="a" * 64,
            package_filename=(
                "empy_studio-1.0.0-"
                "py3-none-any.whl"
            ),
            output_dir=str(
                tmp_path / "dist"
            ),
        )
    )

    manifest = DistributionManifest.load(
        result.manifest_path
    )

    remote_assets = []
    for index, asset in enumerate(
        manifest.assets,
        start=1,
    ):
        remote_assets.append(
            {
                "id": index,
                "name": asset.asset_name,
                "size": asset.size_bytes,
                "state": "uploaded",
                "content_type": (
                    asset.media_type
                ),
                "browser_download_url": (
                    "https://github.com/"
                    "Altpaths/empy-studio/"
                    "releases/download/"
                    f"v1.0.0/{asset.asset_name}"
                ),
                "download_count": 0,
                "digest": (
                    "sha256:"
                    + asset.sha256
                ),
            }
        )

    response = {
        "id": 100,
        "tag_name": "v1.0.0",
        "name": "Empy Studio 1.0.0",
        "html_url": (
            "https://github.com/"
            "Altpaths/empy-studio/"
            "releases/tag/v1.0.0"
        ),
        "draft": False,
        "prerelease": False,
        "published_at": (
            "2026-08-03T12:00:00Z"
        ),
        "assets": remote_assets,
    }

    link_map = sync_distribution_links(
        manifest,
        selection="latest-stable",
        transport=FakeTransport(
            response
        ),
    )

    assert len(link_map.downloads) == 5
    assert all(
        item.url.startswith(
            "https://github.com/"
        )
        for item in link_map.downloads
    )
