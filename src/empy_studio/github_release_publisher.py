from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .artifact_index import (
    ArtifactIndex,
    verify_artifact_index,
)
from .release_manifest import ReleaseManifest

LatestStrategy = Literal[
    "auto",
    "always",
    "never",
    "legacy",
]

DEFAULT_API_VERSION = "2026-03-10"
DEFAULT_API_URL = "https://api.github.com"


class GitHubReleaseError(RuntimeError):
    pass


class GitHubConflictError(GitHubReleaseError):
    pass


class GitHubTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        ...

    def upload_asset(
        self,
        url: str,
        *,
        token: str,
        path: Path,
        media_type: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @classmethod
    def parse(
        cls,
        value: str,
    ) -> GitHubRepository:
        parts = value.strip().split("/")
        if (
            len(parts) != 2
            or not parts[0]
            or not parts[1]
        ):
            raise ValueError(
                "Repository must use OWNER/REPO format"
            )
        return cls(
            owner=parts[0],
            name=parts[1],
        )

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class PublishedAsset:
    asset_id: int
    name: str
    size_bytes: int
    media_type: str
    browser_download_url: str
    state: str
    digest: str | None = None

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
    ) -> PublishedAsset:
        return cls(
            asset_id=int(data["id"]),
            name=str(data["name"]),
            size_bytes=int(data["size"]),
            media_type=str(data["content_type"]),
            browser_download_url=str(
                data["browser_download_url"]
            ),
            state=str(data["state"]),
            digest=(
                str(data["digest"])
                if data.get("digest") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitHubReleasePublication:
    repository: str
    release_id: int
    tag: str
    html_url: str
    draft: bool
    prerelease: bool
    make_latest: str
    assets: tuple[PublishedAsset, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "release_id": self.release_id,
            "tag": self.tag,
            "html_url": self.html_url,
            "draft": self.draft,
            "prerelease": self.prerelease,
            "make_latest": self.make_latest,
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ],
        }


class UrllibGitHubTransport:
    def __init__(
        self,
        *,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero"
            )
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    def _headers(
        self,
        token: str,
        *,
        content_type: str,
    ) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": self.api_version,
            "Content-Type": content_type,
            "User-Agent": "empy-studio-release-manager",
        }

    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        encoded = (
            json.dumps(body).encode("utf-8")
            if body is not None
            else None
        )
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers=self._headers(
                token,
                content_type="application/json",
            ),
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
            if exc.code == 422:
                raise GitHubConflictError(
                    f"GitHub rejected the request: {detail}"
                ) from exc
            raise GitHubReleaseError(
                f"GitHub API request failed "
                f"with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubReleaseError(
                f"GitHub API request failed: {exc}"
            ) from exc

        parsed = json.loads(
            payload.decode("utf-8")
        )
        if not isinstance(parsed, (dict, list)):
            raise GitHubReleaseError(
                "GitHub API returned an unexpected payload"
            )
        return parsed

    def upload_asset(
        self,
        url: str,
        *,
        token: str,
        path: Path,
        media_type: str,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=path.read_bytes(),
            method="POST",
            headers=self._headers(
                token,
                content_type=media_type,
            ),
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
            if exc.code == 422:
                raise GitHubConflictError(
                    f"GitHub rejected asset upload: {detail}"
                ) from exc
            raise GitHubReleaseError(
                f"GitHub asset upload failed "
                f"with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubReleaseError(
                f"GitHub asset upload failed: {exc}"
            ) from exc

        parsed = json.loads(
            payload.decode("utf-8")
        )
        if not isinstance(parsed, dict):
            raise GitHubReleaseError(
                "GitHub asset upload returned "
                "an unexpected payload"
            )
        return parsed


def _latest_value(
    manifest: ReleaseManifest,
    strategy: LatestStrategy,
) -> str:
    if strategy == "always":
        return "true"
    if strategy == "never":
        return "false"
    if strategy == "legacy":
        return "legacy"
    if strategy == "auto":
        return (
            "false"
            if manifest.channel == "prerelease"
            else "true"
        )
    raise ValueError(
        f"Unsupported latest strategy: {strategy}"
    )


def _upload_url(
    template: str,
    asset_name: str,
) -> str:
    base = template.split("{", 1)[0]
    query = urllib.parse.urlencode(
        {"name": asset_name}
    )
    return f"{base}?{query}"


def _expect_dict(
    value: dict[str, Any] | list[dict[str, Any]],
    operation: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitHubReleaseError(
            f"{operation} returned an unexpected list"
        )
    return value


def _expect_list(
    value: dict[str, Any] | list[dict[str, Any]],
    operation: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise GitHubReleaseError(
            f"{operation} returned an unexpected object"
        )
    return value


def publish_github_release(
    manifest: ReleaseManifest,
    artifact_index: ArtifactIndex,
    *,
    repository: str | GitHubRepository,
    token: str,
    release_notes_path: str | Path,
    target_commitish: str = "main",
    latest_strategy: LatestStrategy = "auto",
    draft: bool = False,
    api_url: str = DEFAULT_API_URL,
    transport: GitHubTransport | None = None,
) -> GitHubReleasePublication:
    manifest.validate()
    artifact_index.validate()

    if not token.strip():
        raise ValueError(
            "GitHub token cannot be empty"
        )

    repo = (
        repository
        if isinstance(repository, GitHubRepository)
        else GitHubRepository.parse(repository)
    )

    if artifact_index.product != manifest.product:
        raise ValueError(
            "Artifact index product does not match manifest"
        )
    if artifact_index.version != str(manifest.version):
        raise ValueError(
            "Artifact index version does not match manifest"
        )
    if artifact_index.tag != manifest.tag:
        raise ValueError(
            "Artifact index tag does not match manifest"
        )

    verification_issues = verify_artifact_index(
        artifact_index
    )
    if verification_issues:
        raise ValueError(
            "Artifact verification failed: "
            + "; ".join(verification_issues)
        )

    notes_path = Path(
        release_notes_path
    ).expanduser().resolve()
    if not notes_path.is_file():
        raise FileNotFoundError(notes_path)

    body = notes_path.read_text(
        encoding="utf-8"
    ).strip()
    if not body:
        raise ValueError(
            "Release notes cannot be empty"
        )

    client = transport or UrllibGitHubTransport()
    make_latest = _latest_value(
        manifest,
        latest_strategy,
    )

    create_url = (
        api_url.rstrip("/")
        + f"/repos/{repo.owner}/{repo.name}/releases"
    )
    created = _expect_dict(
        client.request_json(
            "POST",
            create_url,
            token=token,
            body={
                "tag_name": manifest.tag,
                "target_commitish": target_commitish,
                "name": manifest.release_name,
                "body": body,
                "draft": draft,
                "prerelease": (
                    manifest.channel == "prerelease"
                ),
                "make_latest": make_latest,
            },
        ),
        "Create release",
    )

    release_id = int(created["id"])
    upload_template = str(created["upload_url"])
    html_url = str(created["html_url"])

    published_assets: list[PublishedAsset] = []
    root = Path(
        artifact_index.artifact_root
    ).expanduser().resolve()

    for entry in artifact_index.entries:
        path = (
            root / entry.relative_path
        ).resolve()

        response = client.upload_asset(
            _upload_url(
                upload_template,
                entry.name,
            ),
            token=token,
            path=path,
            media_type=entry.media_type,
        )
        published_assets.append(
            PublishedAsset.from_api(response)
        )

    listed = _expect_list(
        client.request_json(
            "GET",
            (
                api_url.rstrip("/")
                + f"/repos/{repo.owner}/{repo.name}"
                + f"/releases/{release_id}/assets"
                + "?per_page=100"
            ),
            token=token,
        ),
        "List release assets",
    )

    listed_by_name = {
        str(item["name"]): item
        for item in listed
    }

    for entry in artifact_index.entries:
        remote = listed_by_name.get(
            entry.name
        )
        if remote is None:
            raise GitHubReleaseError(
                f"Uploaded asset is missing from "
                f"GitHub release: {entry.name}"
            )

        if int(remote["size"]) != entry.size_bytes:
            raise GitHubReleaseError(
                f"Uploaded asset size mismatch: "
                f"{entry.name}"
            )

        if str(remote["state"]) != "uploaded":
            raise GitHubReleaseError(
                f"Uploaded asset is not ready: "
                f"{entry.name}"
            )

        digest = remote.get("digest")
        if (
            digest is not None
            and str(digest)
            != f"sha256:{entry.sha256}"
        ):
            raise GitHubReleaseError(
                f"Uploaded asset digest mismatch: "
                f"{entry.name}"
            )

    return GitHubReleasePublication(
        repository=repo.slug,
        release_id=release_id,
        tag=manifest.tag,
        html_url=html_url,
        draft=bool(created.get("draft", draft)),
        prerelease=bool(
            created.get(
                "prerelease",
                manifest.channel == "prerelease",
            )
        ),
        make_latest=make_latest,
        assets=tuple(published_assets),
    )


def token_from_environment(
    variable: str = "GITHUB_TOKEN",
) -> str:
    token = os.environ.get(variable, "")
    if not token.strip():
        raise RuntimeError(
            f"Required environment variable is missing: "
            f"{variable}"
        )
    return token
