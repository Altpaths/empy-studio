from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.publication_plan import (
    build_publication_plan,
    require_publication_ready,
)


def write_candidate(
    path: Path,
    *,
    ready: bool,
) -> None:
    gates = []
    names = (
        "clean_environment",
        "clean_install",
        "real_project_scenario",
        "security_review",
        "dependency_audit",
        "test_coverage",
        "quality_gate",
        "documentation_en",
        "documentation_fa",
        "example_project",
        "version_alignment",
        "release_assets",
        "download_verification",
    )

    for name in names:
        gates.append(
            {
                "name": name,
                "required": True,
                "status": (
                    "passed"
                    if ready
                    else "pending"
                ),
                "summary": "gate",
                "evidence": [],
            }
        )

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Empy Studio",
                "candidate_version": (
                    "1.0.0-rc.1"
                ),
                "target_version": "1.0.0",
                "branch": (
                    "release/v1.0.0-rc"
                ),
                "commit_sha": (
                    "abcdef1234567890"
                ),
                "gates": gates,
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )


def write_tag_plan(
    path: Path,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository_root": ".",
                "branch": (
                    "release/v1.0.0-rc"
                ),
                "commit_sha": (
                    "abcdef1234567890"
                ),
                "candidate_version": (
                    "1.0.0-rc.1"
                ),
                "candidate_tag": (
                    "v1.0.0-rc.1"
                ),
                "stable_version": "1.0.0",
                "stable_tag": "v1.0.0",
                "annotated": True,
                "push_remote": "origin",
                "create_candidate_tag": True,
                "create_stable_tag": False,
            }
        ),
        encoding="utf-8",
    )


def write_asset_plan(
    path: Path,
) -> None:
    assets = []

    for name in (
        "install-macos-arm64.sh",
        "install-linux-x86_64.sh",
        "install-windows-x86_64.ps1",
    ):
        assets.append(
            {
                "name": name,
                "path": f"dist/{name}",
                "media_type": "text/plain",
                "required": True,
                "sha256": "a" * 64,
                "size_bytes": 100,
            }
        )

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Empy Studio",
                "candidate_version": (
                    "1.0.0-rc.1"
                ),
                "target_version": "1.0.0",
                "candidate_tag": (
                    "v1.0.0-rc.1"
                ),
                "stable_tag": "v1.0.0",
                "release_notes_path": (
                    "release-notes.md"
                ),
                "assets": assets,
            }
        ),
        encoding="utf-8",
    )


def files(
    tmp_path: Path,
    *,
    ready: bool = True,
) -> tuple[Path, Path, Path, Path]:
    candidate = tmp_path / "candidate.json"
    tag_plan = tmp_path / "tag.json"
    asset_plan = tmp_path / "assets.json"
    notes = tmp_path / "notes.md"

    write_candidate(
        candidate,
        ready=ready,
    )
    write_tag_plan(tag_plan)
    write_asset_plan(asset_plan)
    notes.write_text(
        "# Release notes\n",
        encoding="utf-8",
    )

    return (
        candidate,
        tag_plan,
        asset_plan,
        notes,
    )


def test_builds_ready_prerelease_plan(
    tmp_path: Path,
) -> None:
    (
        candidate,
        tag_plan,
        asset_plan,
        notes,
    ) = files(tmp_path)

    output = tmp_path / "publication.json"

    plan = build_publication_plan(
        repository="Altpaths/empy-studio",
        candidate_path=candidate,
        tag_plan_path=tag_plan,
        asset_plan_path=asset_plan,
        release_notes_path=notes,
        output_path=output,
    )

    assert plan.status == "ready"
    assert plan.github_release.prerelease
    assert (
        plan.github_release.make_latest
        == "false"
    )
    assert output.is_file()


def test_generates_direct_github_links(
    tmp_path: Path,
) -> None:
    (
        candidate,
        tag_plan,
        asset_plan,
        notes,
    ) = files(tmp_path)

    plan = build_publication_plan(
        repository="Altpaths/empy-studio",
        candidate_path=candidate,
        tag_plan_path=tag_plan,
        asset_plan_path=asset_plan,
        release_notes_path=notes,
        output_path=(
            tmp_path / "publication.json"
        ),
    )

    assert all(
        link.direct_url.startswith(
            "https://github.com/"
        )
        for link in plan.website_links
    )
    assert all(
        "/releases/download/"
        in link.direct_url
        for link in plan.website_links
    )


def test_pending_candidate_blocks_publication(
    tmp_path: Path,
) -> None:
    (
        candidate,
        tag_plan,
        asset_plan,
        notes,
    ) = files(
        tmp_path,
        ready=False,
    )

    plan = build_publication_plan(
        repository="Altpaths/empy-studio",
        candidate_path=candidate,
        tag_plan_path=tag_plan,
        asset_plan_path=asset_plan,
        release_notes_path=notes,
        output_path=(
            tmp_path / "publication.json"
        ),
    )

    assert plan.status == "blocked"

    with pytest.raises(
        RuntimeError,
        match="blocked",
    ):
        require_publication_ready(plan)


def test_stable_channel_uses_latest(
    tmp_path: Path,
) -> None:
    (
        candidate,
        tag_plan,
        asset_plan,
        notes,
    ) = files(tmp_path)

    plan = build_publication_plan(
        repository="Altpaths/empy-studio",
        candidate_path=candidate,
        tag_plan_path=tag_plan,
        asset_plan_path=asset_plan,
        release_notes_path=notes,
        output_path=(
            tmp_path / "stable.json"
        ),
        channel="stable",
    )

    assert not plan.github_release.prerelease
    assert (
        plan.github_release.make_latest
        == "true"
    )
    assert (
        plan.github_release.tag
        == "v1.0.0"
    )


def test_rejects_non_github_website_link() -> None:
    from empy_studio.publication_plan import (
        WebsiteDownloadLink,
    )

    with pytest.raises(
        ValueError,
        match="GitHub",
    ):
        WebsiteDownloadLink(
            target="macos-arm64",
            asset_name=(
                "install-macos-arm64.sh"
            ),
            direct_url=(
                "https://example.com/download"
            ),
        ).validate()
