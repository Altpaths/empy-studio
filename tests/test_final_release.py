from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.final_release import (
    EvidenceInput,
    FinalReleaseConfig,
    finalize_release_candidate,
    require_final_release_ready,
)

GATE_NAMES = (
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


def write_candidate(
    path: Path,
) -> None:
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
                "gates": [
                    {
                        "name": name,
                        "required": True,
                        "status": "pending",
                        "summary": "pending",
                        "evidence": [],
                    }
                    for name in GATE_NAMES
                ],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )


def write_publication(
    path: Path,
    *,
    ready: bool = True,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": "prerelease",
                "status": (
                    "ready"
                    if ready
                    else "blocked"
                ),
                "github_release": {
                    "repository": (
                        "Altpaths/empy-studio"
                    ),
                    "tag": "v1.0.0-rc.1",
                    "name": (
                        "Empy Studio 1.0.0-rc.1"
                    ),
                    "body_path": (
                        "/tmp/release-notes.md"
                    ),
                    "target_commitish": (
                        "abcdef1234567890"
                    ),
                    "draft": False,
                    "prerelease": True,
                    "make_latest": "false",
                },
                "assets": [
                    {
                        "name": "asset.whl",
                        "path": "dist/asset.whl",
                        "media_type": (
                            "application/zip"
                        ),
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                    }
                ],
                "website_links": [
                    {
                        "target": "macos-arm64",
                        "asset_name": (
                            "install-macos-arm64.sh"
                        ),
                        "direct_url": (
                            "https://github.com/"
                            "Altpaths/empy-studio/"
                            "releases/download/"
                            "v1.0.0-rc.1/"
                            "install-macos-arm64.sh"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def evidence_file(
    path: Path,
    *,
    status: str = "passed",
) -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
            }
        ),
        encoding="utf-8",
    )


def config(
    tmp_path: Path,
    *,
    failed: bool = False,
) -> FinalReleaseConfig:
    candidate = tmp_path / "candidate.json"
    publication = (
        tmp_path / "publication.json"
    )

    write_candidate(candidate)
    write_publication(publication)

    evidence_inputs = []
    mappings = (
        (
            (
                "clean_environment",
                "clean_install",
            ),
            "clean.json",
        ),
        (
            (
                "real_project_scenario",
            ),
            "scenario.json",
        ),
        (
            (
                "security_review",
                "dependency_audit",
            ),
            "security.json",
        ),
        (
            (
                "test_coverage",
                "quality_gate",
            ),
            "quality.json",
        ),
        (
            (
                "documentation_en",
                "documentation_fa",
                "example_project",
            ),
            "docs.json",
        ),
        (
            (
                "version_alignment",
            ),
            "version.json",
        ),
        (
            (
                "release_assets",
            ),
            "assets.json",
        ),
    )

    for index, (
        gates,
        filename,
    ) in enumerate(mappings):
        path = tmp_path / filename
        evidence_file(
            path,
            status=(
                "failed"
                if failed and index == 0
                else "passed"
            ),
        )
        evidence_inputs.append(
            EvidenceInput(
                gate_names=gates,
                path=str(path),
                kind=filename,
            )
        )

    return FinalReleaseConfig(
        candidate_path=str(candidate),
        publication_plan_path=str(
            publication
        ),
        updated_candidate_path=str(
            tmp_path / "candidate-final.json"
        ),
        handoff_path=str(
            tmp_path / "handoff.json"
        ),
        report_path=str(
            tmp_path / "report.json"
        ),
        evidence_inputs=tuple(
            evidence_inputs
        ),
    )


def test_final_release_ready(
    tmp_path: Path,
) -> None:
    release_config = config(tmp_path)

    report = finalize_release_candidate(
        release_config,
        link_verifier=lambda url: True,
    )

    assert report.status == "ready"
    assert report.blockers == ()
    assert Path(
        release_config.handoff_path
    ).is_file()
    assert Path(
        release_config.updated_candidate_path
    ).is_file()


def test_failed_evidence_blocks_release(
    tmp_path: Path,
) -> None:
    release_config = config(
        tmp_path,
        failed=True,
    )

    report = finalize_release_candidate(
        release_config,
        link_verifier=lambda url: True,
    )

    assert report.status == "blocked"
    assert "clean_environment" in (
        report.blockers
    )

    with pytest.raises(
        RuntimeError,
        match="clean_environment",
    ):
        require_final_release_ready(
            report
        )


def test_failed_download_blocks_release(
    tmp_path: Path,
) -> None:
    release_config = config(tmp_path)

    report = finalize_release_candidate(
        release_config,
        link_verifier=lambda url: False,
    )

    assert report.status == "blocked"
    assert "download:macos-arm64" in (
        report.blockers
    )


def test_blocked_publication_plan_blocks(
    tmp_path: Path,
) -> None:
    release_config = config(tmp_path)
    write_publication(
        Path(
            release_config.publication_plan_path
        ),
        ready=False,
    )

    report = finalize_release_candidate(
        release_config,
        link_verifier=lambda url: True,
    )

    assert "publication_plan" in (
        report.blockers
    )


def test_handoff_contains_only_commands(
    tmp_path: Path,
) -> None:
    release_config = config(tmp_path)

    finalize_release_candidate(
        release_config,
        link_verifier=lambda url: True,
    )

    handoff = json.loads(
        Path(
            release_config.handoff_path
        ).read_text(
            encoding="utf-8"
        )
    )

    assert handoff["status"] == "ready"
    assert any(
        command.startswith(
            "git tag -a"
        )
        for command in handoff["commands"]
    )
    assert any(
        command.startswith(
            "git push origin"
        )
        for command in handoff["commands"]
    )
