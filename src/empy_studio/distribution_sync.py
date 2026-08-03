from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .distribution_manifest import (
    DistributionAsset,
    DistributionManifest,
)
from .platform_support import (
    DistributionTarget,
    parse_target,
)

ReleaseSelection = Literal[
    "latest-stable",
    "latest-prerelease",
    "tag",
]

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_API_VERSION = "2022-11-28"


class DistributionSyncError(RuntimeError):
    pass


class DistributionReleaseNotFound(
    DistributionSyncError
):
    pass


class DistributionAssetMismatch(
    DistributionSyncError
):
    pass


class DistributionTransport(Protocol):
    def request_json(
        self,
        url: str,
        *,
        token: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class RemoteReleaseAsset:
    asset_id: int
    name: str
    size_bytes: int
    state: str
    content_type: str
    browser_download_url: str
    download_count: int
    digest: str | None = None

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
    ) -> RemoteReleaseAsset:
        return cls(
            asset_id=int(data["id"]),
            name=str(data["name"]),
            size_bytes=int(data["size"]),
            state=str(data["state"]),
            content_type=str(data["content_type"]),
            browser_download_url=str(
                data["browser_download_url"]
            ),
            download_count=int(
                data.get("download_count", 0)
            ),
            digest=(
                str(data["digest"])
                if data.get("digest") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RemoteDistributionRelease:
    release_id: int
    tag: str
    name: str
    html_url: str
    draft: bool
    prerelease: bool
    published_at: str | None
    assets: tuple[RemoteReleaseAsset, ...]

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
    ) -> RemoteDistributionRelease:
        raw_assets = data.get("assets", [])
        if not isinstance(raw_assets, list):
            raise DistributionSyncError(
                "GitHub release assets must be a list"
            )

        return cls(
            release_id=int(data["id"]),
            tag=str(data["tag_name"]),
            name=str(data.get("name") or ""),
            html_url=str(data["html_url"]),
            draft=bool(data.get("draft", False)),
            prerelease=bool(
                data.get("prerelease", False)
            ),
            published_at=(
                str(data["published_at"])
                if data.get("published_at")
                is not None
                else None
            ),
            assets=tuple(
                RemoteReleaseAsset.from_api(item)
                for item in raw_assets
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "tag": self.tag,
            "name": self.name,
            "html_url": self.html_url,
            "draft": self.draft,
            "prerelease": self.prerelease,
            "published_at": self.published_at,
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ],
        }


@dataclass(frozen=True)
class DistributionDownload:
    target: DistributionTarget
    asset_name: str
    url: str
    sha256: str
    size_bytes: int
    media_type: str
    download_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DistributionLinkMap:
    schema_version: int
    repository: str
    version: str
    release_tag: str
    release_url: str
    prerelease: bool
    downloads: tuple[DistributionDownload, ...]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported distribution link-map schema"
            )
        if self.release_tag != f"v{self.version}":
            raise ValueError(
                "Distribution link-map tag "
                "must match v<version>"
            )

        targets = [
            item.target
            for item in self.downloads
        ]
        if len(targets) != len(set(targets)):
            raise ValueError(
                "Distribution link-map targets "
                "must be unique"
            )

    def download_for_target(
        self,
        target: DistributionTarget,
    ) -> DistributionDownload:
        for item in self.downloads:
            if item.target == target:
                return item

        raise KeyError(
            f"No download URL for target: {target}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "version": self.version,
            "release_tag": self.release_tag,
            "release_url": self.release_url,
            "prerelease": self.prerelease,
            "downloads": [
                item.to_dict()
                for item in self.downloads
            ],
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    @classmethod
    def load(
        cls,
        source: str | Path,
    ) -> DistributionLinkMap:
        path = Path(source).expanduser().resolve()
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError(
                "Distribution link map must contain "
                "a JSON object"
            )

        raw_downloads = value.get("downloads", [])
        if not isinstance(raw_downloads, list):
            raise TypeError(
                "Distribution link-map downloads "
                "must be a list"
            )

        link_map = cls(
            schema_version=int(
                value["schema_version"]
            ),
            repository=str(value["repository"]),
            version=str(value["version"]),
            release_tag=str(
                value["release_tag"]
            ),
            release_url=str(
                value["release_url"]
            ),
            prerelease=bool(
                value["prerelease"]
            ),
            downloads=tuple(
                DistributionDownload(
                    target=parse_target(
                        str(item["target"])
                    ).target,
                    asset_name=str(
                        item["asset_name"]
                    ),
                    url=str(item["url"]),
                    sha256=str(
                        item["sha256"]
                    ),
                    size_bytes=int(
                        item["size_bytes"]
                    ),
                    media_type=str(
                        item["media_type"]
                    ),
                    download_count=int(
                        item["download_count"]
                    ),
                )
                for item in raw_downloads
            ),
        )
        link_map.validate()
        return link_map


class UrllibDistributionTransport:
    def __init__(
        self,
        *,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        url: str,
        *,
        token: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        headers = {
            "Accept": (
                "application/vnd.github+json"
            ),
            "X-GitHub-Api-Version": (
                self.api_version
            ),
            "User-Agent": (
                "empy-studio-distribution-sync"
            ),
        }

        if token:
            headers["Authorization"] = (
                f"Bearer {token}"
            )

        request = urllib.request.Request(
            url,
            method="GET",
            headers=headers,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise DistributionSyncError(
                f"GitHub API failed with "
                f"HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise DistributionSyncError(
                f"GitHub API request failed: {exc}"
            ) from exc

        parsed = json.loads(
            payload.decode("utf-8")
        )
        if not isinstance(parsed, (dict, list)):
            raise DistributionSyncError(
                "GitHub API returned an "
                "unexpected payload"
            )
        return parsed


def _repository_parts(
    repository: str,
) -> tuple[str, str]:
    parts = repository.split("/")

    if (
        len(parts) != 2
        or not parts[0]
        or not parts[1]
    ):
        raise ValueError(
            "Repository must use OWNER/REPO format"
        )

    return parts[0], parts[1]


def resolve_remote_release(
    *,
    repository: str,
    selection: ReleaseSelection,
    transport: DistributionTransport,
    token: str | None = None,
    tag: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> RemoteDistributionRelease:
    owner, name = _repository_parts(repository)
    base = (
        api_url.rstrip("/")
        + f"/repos/{owner}/{name}/releases"
    )

    if selection == "latest-stable":
        payload = transport.request_json(
            base + "/latest",
            token=token,
        )
        if not isinstance(payload, dict):
            raise DistributionSyncError(
                "Latest release response "
                "must be an object"
            )
        release = RemoteDistributionRelease.from_api(
            payload
        )

        if release.draft or release.prerelease:
            raise DistributionReleaseNotFound(
                "Latest stable release was not found"
            )
        return release

    if selection == "tag":
        if not tag:
            raise ValueError(
                "Tag selection requires a tag"
            )

        encoded = urllib.parse.quote(
            tag,
            safe="",
        )
        payload = transport.request_json(
            base + f"/tags/{encoded}",
            token=token,
        )
        if not isinstance(payload, dict):
            raise DistributionSyncError(
                "Tagged release response "
                "must be an object"
            )
        release = RemoteDistributionRelease.from_api(
            payload
        )
        if release.draft:
            raise DistributionReleaseNotFound(
                f"Release {tag} is still a draft"
            )
        return release

    if selection == "latest-prerelease":
        payload = transport.request_json(
            base + "?per_page=100",
            token=token,
        )
        if not isinstance(payload, list):
            raise DistributionSyncError(
                "Release-list response must be a list"
            )

        releases = [
            RemoteDistributionRelease.from_api(item)
            for item in payload
        ]

        candidates = [
            release
            for release in releases
            if (
                not release.draft
                and release.prerelease
            )
        ]

        if not candidates:
            raise DistributionReleaseNotFound(
                "Latest prerelease was not found"
            )

        return max(
            candidates,
            key=lambda item: (
                item.published_at or "",
                item.release_id,
            ),
        )

    raise ValueError(
        f"Unsupported release selection: {selection}"
    )


def _verify_remote_asset(
    expected: DistributionAsset,
    remote: RemoteReleaseAsset,
) -> None:
    if remote.state != "uploaded":
        raise DistributionAssetMismatch(
            f"Asset is not uploaded: {remote.name}"
        )

    if remote.size_bytes != expected.size_bytes:
        raise DistributionAssetMismatch(
            f"Asset size mismatch: {remote.name}"
        )

    if remote.content_type != expected.media_type:
        raise DistributionAssetMismatch(
            f"Asset media type mismatch: "
            f"{remote.name}"
        )

    if (
        remote.digest is not None
        and remote.digest
        != f"sha256:{expected.sha256}"
    ):
        raise DistributionAssetMismatch(
            f"Asset digest mismatch: "
            f"{remote.name}"
        )


def build_distribution_link_map(
    manifest: DistributionManifest,
    release: RemoteDistributionRelease,
) -> DistributionLinkMap:
    manifest.validate()

    if release.tag != manifest.release_tag:
        raise DistributionAssetMismatch(
            "GitHub release tag does not "
            "match Distribution Manifest"
        )

    remote_by_name = {
        asset.name: asset
        for asset in release.assets
    }

    downloads: list[DistributionDownload] = []

    for expected in manifest.assets:
        remote = remote_by_name.get(
            expected.asset_name
        )

        if remote is None:
            raise DistributionAssetMismatch(
                "Required release asset is missing: "
                f"{expected.asset_name}"
            )

        _verify_remote_asset(
            expected,
            remote,
        )

        downloads.append(
            DistributionDownload(
                target=expected.target,
                asset_name=expected.asset_name,
                url=remote.browser_download_url,
                sha256=expected.sha256,
                size_bytes=expected.size_bytes,
                media_type=expected.media_type,
                download_count=(
                    remote.download_count
                ),
            )
        )

    link_map = DistributionLinkMap(
        schema_version=1,
        repository=manifest.repository,
        version=str(manifest.version),
        release_tag=manifest.release_tag,
        release_url=release.html_url,
        prerelease=release.prerelease,
        downloads=tuple(
            sorted(
                downloads,
                key=lambda item: item.target,
            )
        ),
    )
    link_map.validate()
    return link_map


def sync_distribution_links(
    manifest: DistributionManifest,
    *,
    selection: ReleaseSelection,
    transport: DistributionTransport,
    token: str | None = None,
    tag: str | None = None,
    api_url: str = DEFAULT_API_URL,
) -> DistributionLinkMap:
    release = resolve_remote_release(
        repository=manifest.repository,
        selection=selection,
        transport=transport,
        token=token,
        tag=tag,
        api_url=api_url,
    )
    return build_distribution_link_map(
        manifest,
        release,
    )
