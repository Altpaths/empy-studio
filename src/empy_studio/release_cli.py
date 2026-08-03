from __future__ import annotations

from typing import Any, cast

from .artifact_index import ArtifactIndex
from .changelog_validator import (
    validate_release_changelog,
)
from .github_release_publisher import (
    LatestStrategy,
    UrllibGitHubTransport,
    token_from_environment,
)
from .release_builder import build_release
from .release_manifest import ReleaseManifest
from .release_pipeline import (
    publish_release_pipeline,
)
from .release_tag import create_controlled_tag


def release_validate_command(
    manifest_path: str,
    changelog_path: str,
) -> dict[str, Any]:
    manifest = ReleaseManifest.load(
        manifest_path
    )
    return validate_release_changelog(
        changelog_path,
        manifest.version,
    ).to_dict()


def release_build_command(
    manifest_path: str,
    source_root: str,
    include_paths: list[str],
    changelog_path: str,
    output_dir: str,
) -> dict[str, Any]:
    manifest = ReleaseManifest.load(
        manifest_path
    )
    return build_release(
        manifest,
        source_root=source_root,
        include_paths=include_paths,
        changelog_path=changelog_path,
        output_dir=output_dir,
    ).to_dict()


def release_tag_command(
    manifest_path: str,
    repository_root: str,
    expected_branch: str,
    push: bool,
    remote: str,
) -> dict[str, Any]:
    manifest = ReleaseManifest.load(
        manifest_path
    )
    return create_controlled_tag(
        manifest,
        repository_root,
        expected_branch=expected_branch,
        push=push,
        remote=remote,
    ).to_dict()


def release_publish_command(
    manifest_path: str,
    artifact_index_path: str,
    release_notes_path: str,
    repository_root: str,
    repository: str,
    token_env: str,
    rollback_dir: str,
    expected_branch: str,
    workflow_name: str,
    target_commitish: str,
    latest_strategy: str,
    draft: bool,
) -> dict[str, Any]:
    token = token_from_environment(
        token_env
    )
    transport = UrllibGitHubTransport()

    return publish_release_pipeline(
        manifest_path=manifest_path,
        artifact_index_path=artifact_index_path,
        release_notes_path=release_notes_path,
        repository_root=repository_root,
        repository=repository,
        token=token,
        transport=transport,
        rollback_dir=rollback_dir,
        expected_branch=expected_branch,
        workflow_name=workflow_name,
        target_commitish=target_commitish,
        latest_strategy=cast(
            LatestStrategy,
            latest_strategy,
        ),
        draft=draft,
    ).to_dict()


def release_inspect_command(
    manifest_path: str,
    artifact_index_path: str,
) -> dict[str, Any]:
    manifest = ReleaseManifest.load(
        manifest_path
    )
    index = ArtifactIndex.load(
        artifact_index_path
    )

    return {
        "manifest": manifest.to_dict(),
        "artifact_index": index.to_dict(),
        "consistent": (
            manifest.product == index.product
            and str(manifest.version)
            == index.version
            and manifest.tag == index.tag
        ),
    }
