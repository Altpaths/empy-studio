from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .artifact_index import ArtifactIndex
from .github_release_publisher import (
    GitHubReleasePublication,
    GitHubTransport,
    LatestStrategy,
    publish_github_release,
)
from .release_guard import (
    ReleaseControlTransport,
    ReleaseGuardResult,
    ReleaseRollbackError,
    guard_release,
    rollback_failed_release,
)
from .release_manifest import ReleaseManifest


class UnifiedReleaseTransport(
    GitHubTransport,
    ReleaseControlTransport,
    Protocol,
):
    pass


@dataclass(frozen=True)
class ReleasePipelineResult:
    status: str
    manifest_path: str
    artifact_index_path: str
    guard: ReleaseGuardResult
    publication: GitHubReleasePublication

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifest_path": self.manifest_path,
            "artifact_index_path": self.artifact_index_path,
            "guard": self.guard.to_dict(),
            "publication": self.publication.to_dict(),
        }


class _TrackingTransport:
    def __init__(
        self,
        delegate: UnifiedReleaseTransport,
    ) -> None:
        self.delegate = delegate
        self.created_release_id: int | None = None

    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        result = self.delegate.request_json(
            method,
            url,
            token=token,
            body=body,
        )
        if (
            method == "POST"
            and url.rstrip("/").endswith("/releases")
            and isinstance(result, dict)
            and result.get("id") is not None
        ):
            self.created_release_id = int(result["id"])
        return result

    def upload_asset(
        self,
        url: str,
        *,
        token: str,
        path: Path,
        media_type: str,
    ) -> dict[str, Any]:
        return self.delegate.upload_asset(
            url,
            token=token,
            path=path,
            media_type=media_type,
        )


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def publish_release_pipeline(
    *,
    manifest_path: str | Path,
    artifact_index_path: str | Path,
    release_notes_path: str | Path,
    repository_root: str | Path,
    repository: str,
    token: str,
    transport: UnifiedReleaseTransport,
    rollback_dir: str | Path,
    api_url: str = "https://api.github.com",
    expected_branch: str = "main",
    workflow_name: str = "CI",
    target_commitish: str = "main",
    latest_strategy: LatestStrategy = "auto",
    draft: bool = False,
) -> ReleasePipelineResult:
    resolved_manifest = (
        Path(manifest_path).expanduser().resolve()
    )
    resolved_index = (
        Path(artifact_index_path).expanduser().resolve()
    )

    manifest = ReleaseManifest.load(
        resolved_manifest
    )
    index = ArtifactIndex.load(
        resolved_index
    )

    guard = guard_release(
        manifest,
        index,
        repository_root=repository_root,
        repository=repository,
        token=token,
        transport=transport,
        api_url=api_url,
        expected_branch=expected_branch,
        workflow_name=workflow_name,
    )

    tracking = _TrackingTransport(transport)

    try:
        publication = publish_github_release(
            manifest,
            index,
            repository=repository,
            token=token,
            release_notes_path=release_notes_path,
            target_commitish=target_commitish,
            latest_strategy=latest_strategy,
            draft=draft,
            api_url=api_url,
            transport=tracking,
        )
    except Exception as exc:
        if tracking.created_release_id is None:
            raise

        rollback = rollback_failed_release(
            transport,
            api_url=api_url,
            repository=repository,
            token=token,
            release_id=tracking.created_release_id,
            manifest=manifest,
            commit_sha=guard.commit_sha,
            reason=str(exc),
            artifact_index=index,
        )
        rollback_path = (
            Path(rollback_dir).expanduser().resolve()
            / f"rollback-{manifest.tag}.json"
        )
        rollback.save(rollback_path)

        raise ReleaseRollbackError(
            "Release publication failed and was rolled back; "
            f"rollback metadata: {rollback_path}"
        ) from exc

    result = ReleasePipelineResult(
        status="published",
        manifest_path=str(resolved_manifest),
        artifact_index_path=str(resolved_index),
        guard=guard,
        publication=publication,
    )

    result_path = (
        Path(rollback_dir).expanduser().resolve()
        / f"publication-{manifest.tag}.json"
    )
    _write_json_atomic(
        result_path,
        result.to_dict(),
    )

    return result
