from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .release_candidate import ReleaseCandidate
from .release_tag_plan import ControlledTagPlan

PublicationChannel = Literal[
    "prerelease",
    "stable",
]


@dataclass(frozen=True)
class PublicationAsset:
    name: str
    path: str
    media_type: str
    sha256: str
    size_bytes: int

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Publication asset name cannot be empty"
            )
        if Path(self.name).name != self.name:
            raise ValueError(
                "Publication asset name must not contain a path"
            )
        if not self.path.strip():
            raise ValueError(
                "Publication asset path cannot be empty"
            )
        if not self.media_type.strip():
            raise ValueError(
                "Publication asset media type cannot be empty"
            )
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.sha256.lower()
        ):
            raise ValueError(
                "Publication asset SHA-256 must be valid"
            )
        if self.size_bytes <= 0:
            raise ValueError(
                "Publication asset size must be positive"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GitHubReleaseRequest:
    repository: str
    tag: str
    name: str
    body_path: str
    target_commitish: str
    draft: bool
    prerelease: bool
    make_latest: str

    def validate(self) -> None:
        parts = self.repository.split("/")
        if (
            len(parts) != 2
            or not parts[0]
            or not parts[1]
        ):
            raise ValueError(
                "Repository must use OWNER/REPO format"
            )
        if not self.tag.strip():
            raise ValueError(
                "Release tag cannot be empty"
            )
        if not self.name.strip():
            raise ValueError(
                "Release name cannot be empty"
            )
        if not self.body_path.strip():
            raise ValueError(
                "Release body path cannot be empty"
            )
        if len(self.target_commitish) < 7:
            raise ValueError(
                "target_commitish is too short"
            )
        if self.make_latest not in {
            "true",
            "false",
            "legacy",
        }:
            raise ValueError(
                "Unsupported make_latest strategy"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WebsiteDownloadLink:
    target: str
    asset_name: str
    direct_url: str

    def validate(self) -> None:
        if not self.target.strip():
            raise ValueError(
                "Website target cannot be empty"
            )
        if not self.asset_name.strip():
            raise ValueError(
                "Website asset name cannot be empty"
            )
        if not self.direct_url.startswith(
            "https://github.com/"
        ):
            raise ValueError(
                "Website download URL must point "
                "directly to GitHub"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublicationPlan:
    schema_version: int
    channel: PublicationChannel
    status: str
    candidate_path: str
    tag_plan_path: str
    asset_plan_path: str
    github_release: GitHubReleaseRequest
    assets: tuple[PublicationAsset, ...]
    website_links: tuple[WebsiteDownloadLink, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported publication-plan schema"
            )
        if self.channel not in {
            "prerelease",
            "stable",
        }:
            raise ValueError(
                "Unsupported publication channel"
            )
        if self.status not in {
            "ready",
            "blocked",
        }:
            raise ValueError(
                "Unsupported publication status"
            )
        if not self.assets:
            raise ValueError(
                "Publication plan must contain assets"
            )

        names = [
            asset.name
            for asset in self.assets
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                "Publication asset names must be unique"
            )

        targets = [
            link.target
            for link in self.website_links
        ]
        if len(targets) != len(set(targets)):
            raise ValueError(
                "Website download targets must be unique"
            )

        self.github_release.validate()
        for asset in self.assets:
            asset.validate()
        for link in self.website_links:
            link.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "channel": self.channel,
            "status": self.status,
            "ready": self.ready,
            "candidate_path": self.candidate_path,
            "tag_plan_path": self.tag_plan_path,
            "asset_plan_path": self.asset_plan_path,
            "github_release": (
                self.github_release.to_dict()
            ),
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ],
            "website_links": [
                link.to_dict()
                for link in self.website_links
            ],
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

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


def _github_asset_url(
    repository: str,
    tag: str,
    asset_name: str,
) -> str:
    return (
        f"https://github.com/{repository}/"
        f"releases/download/{tag}/{asset_name}"
    )


def build_publication_plan(
    *,
    repository: str,
    candidate_path: str | Path,
    tag_plan_path: str | Path,
    asset_plan_path: str | Path,
    release_notes_path: str | Path,
    output_path: str | Path,
    channel: PublicationChannel = "prerelease",
) -> PublicationPlan:
    candidate = ReleaseCandidate.load(
        candidate_path
    )

    tag_value = json.loads(
        Path(tag_plan_path)
        .expanduser()
        .resolve()
        .read_text(encoding="utf-8")
    )
    if not isinstance(tag_value, dict):
        raise TypeError(
            "Tag plan must contain a JSON object"
        )

    tag_plan = ControlledTagPlan(
        schema_version=int(
            tag_value["schema_version"]
        ),
        repository_root=str(
            tag_value["repository_root"]
        ),
        branch=str(tag_value["branch"]),
        commit_sha=str(
            tag_value["commit_sha"]
        ),
        candidate_version=(
            candidate.candidate_version
        ),
        candidate_tag=str(
            tag_value["candidate_tag"]
        ),
        stable_version=(
            candidate.target_version
        ),
        stable_tag=str(
            tag_value["stable_tag"]
        ),
        annotated=bool(
            tag_value["annotated"]
        ),
        push_remote=str(
            tag_value["push_remote"]
        ),
        create_candidate_tag=bool(
            tag_value["create_candidate_tag"]
        ),
        create_stable_tag=bool(
            tag_value["create_stable_tag"]
        ),
    )
    tag_plan.validate()

    asset_value = json.loads(
        Path(asset_plan_path)
        .expanduser()
        .resolve()
        .read_text(encoding="utf-8")
    )
    if not isinstance(asset_value, dict):
        raise TypeError(
            "Asset plan must contain a JSON object"
        )

    raw_assets = asset_value.get(
        "assets",
        [],
    )
    if not isinstance(raw_assets, list):
        raise TypeError(
            "Asset plan assets must be a list"
        )

    assets = tuple(
        PublicationAsset(
            name=str(item["name"]),
            path=str(item["path"]),
            media_type=str(
                item["media_type"]
            ),
            sha256=str(item["sha256"]),
            size_bytes=int(
                item["size_bytes"]
            ),
        )
        for item in raw_assets
        if (
            item.get("sha256") is not None
            and item.get("size_bytes")
            is not None
        )
    )

    tag = (
        tag_plan.candidate_tag
        if channel == "prerelease"
        else tag_plan.stable_tag
    )

    release_request = GitHubReleaseRequest(
        repository=repository,
        tag=tag,
        name=(
            f"Empy Studio "
            f"{candidate.candidate_version}"
            if channel == "prerelease"
            else (
                f"Empy Studio "
                f"{candidate.target_version}"
            )
        ),
        body_path=str(
            Path(release_notes_path)
            .expanduser()
            .resolve()
        ),
        target_commitish=(
            tag_plan.commit_sha
        ),
        draft=False,
        prerelease=(
            channel == "prerelease"
        ),
        make_latest=(
            "false"
            if channel == "prerelease"
            else "true"
        ),
    )

    platform_assets = {
        asset.name: asset
        for asset in assets
        if asset.name.startswith(
            "install-"
        )
    }

    website_links = tuple(
        WebsiteDownloadLink(
            target=asset.name.removeprefix(
                "install-"
            ).removesuffix(
                ".sh"
            ).removesuffix(
                ".ps1"
            ),
            asset_name=asset.name,
            direct_url=_github_asset_url(
                repository,
                tag,
                asset.name,
            ),
        )
        for asset in sorted(
            platform_assets.values(),
            key=lambda item: item.name,
        )
    )

    required_ready = (
        candidate.decision == "ready"
        and bool(assets)
        and all(
            asset.name in {
                item.name
                for item in assets
            }
            for asset in assets
        )
    )

    plan = PublicationPlan(
        schema_version=1,
        channel=channel,
        status=(
            "ready"
            if required_ready
            else "blocked"
        ),
        candidate_path=str(
            Path(candidate_path)
            .expanduser()
            .resolve()
        ),
        tag_plan_path=str(
            Path(tag_plan_path)
            .expanduser()
            .resolve()
        ),
        asset_plan_path=str(
            Path(asset_plan_path)
            .expanduser()
            .resolve()
        ),
        github_release=release_request,
        assets=assets,
        website_links=website_links,
    )
    plan.validate()
    plan.save(output_path)
    return plan


def require_publication_ready(
    plan: PublicationPlan,
) -> None:
    plan.validate()

    if plan.ready:
        return

    raise RuntimeError(
        "Publication plan is blocked"
    )
