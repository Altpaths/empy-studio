from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.release_asset_plan import (
    default_release_asset_plan,
    materialize_asset_plan,
)
from empy_studio.release_tag_plan import (
    ControlledTagPlan,
)
from empy_studio.release_version import (
    ReleaseVersion,
)
from empy_studio.version_alignment import (
    VersionAlignmentConfig,
    VersionSource,
    default_version_alignment_config,
    require_version_alignment,
    run_version_alignment,
)


def project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "project"
    root.mkdir()

    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "empy-studio"\n'
        'version = "1.0.0-rc.1"\n',
        encoding="utf-8",
    )

    package = (
        root / "src" / "empy_studio"
    )
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '__version__ = "1.0.0-rc.1"\n',
        encoding="utf-8",
    )

    return root


def test_default_version_alignment_passes(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    evidence = run_version_alignment(
        default_version_alignment_config(
            root,
            tmp_path / "version.json",
        )
    )

    assert evidence.status == "passed"
    assert len(evidence.observations) == 2


def test_version_mismatch_fails(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root / "pyproject.toml"
    ).write_text(
        "[project]\n"
        'version = "0.9.0"\n',
        encoding="utf-8",
    )

    evidence = run_version_alignment(
        default_version_alignment_config(
            root,
            tmp_path / "version.json",
        )
    )

    assert evidence.status == "failed"

    with pytest.raises(
        RuntimeError,
        match="pyproject.toml",
    ):
        require_version_alignment(
            evidence
        )


def test_optional_version_source_may_be_absent(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "src"
        / "empy_studio"
        / "__init__.py"
    ).unlink()

    evidence = run_version_alignment(
        default_version_alignment_config(
            root,
            tmp_path / "version.json",
        )
    )

    assert evidence.status == "passed"


def test_rejects_unsafe_version_source(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    with pytest.raises(
        ValueError,
        match="safe relative paths",
    ):
        VersionAlignmentConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "version.json"
            ),
            candidate_version=(
                ReleaseVersion.parse(
                    "1.0.0-rc.1"
                )
            ),
            target_version=(
                ReleaseVersion.parse(
                    "1.0.0"
                )
            ),
            sources=(
                VersionSource(
                    path="../outside",
                    kind="text",
                    pattern=(
                        r"(?P<version>.+)"
                    ),
                ),
            ),
        ).validate()


def test_materializes_release_asset_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    plan = default_release_asset_plan()

    for asset in plan.assets:
        path = root / asset.path
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_bytes(
            asset.name.encode("utf-8")
        )

    materialized = materialize_asset_plan(
        plan,
        project_root=root,
    )

    assert materialized.ready
    assert all(
        item.sha256 is not None
        and item.size_bytes is not None
        for item in materialized.assets
    )


def test_missing_required_asset_blocks_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    materialized = materialize_asset_plan(
        default_release_asset_plan(),
        project_root=root,
    )

    assert materialized.ready is False


def test_controlled_tag_plan_blocks_stable_tag() -> None:
    with pytest.raises(
        ValueError,
        match="Stable tag",
    ):
        ControlledTagPlan(
            schema_version=1,
            repository_root=".",
            branch="release/v1.0.0-rc",
            commit_sha="abcdef1234567890",
            candidate_version=(
                ReleaseVersion.parse(
                    "1.0.0-rc.1"
                )
            ),
            candidate_tag="v1.0.0-rc.1",
            stable_version=(
                ReleaseVersion.parse(
                    "1.0.0"
                )
            ),
            stable_tag="v1.0.0",
            annotated=True,
            push_remote="origin",
            create_candidate_tag=True,
            create_stable_tag=True,
        ).validate()


def test_valid_controlled_tag_plan() -> None:
    plan = ControlledTagPlan(
        schema_version=1,
        repository_root=".",
        branch="release/v1.0.0-rc",
        commit_sha="abcdef1234567890",
        candidate_version=(
            ReleaseVersion.parse(
                "1.0.0-rc.1"
            )
        ),
        candidate_tag="v1.0.0-rc.1",
        stable_version=(
            ReleaseVersion.parse(
                "1.0.0"
            )
        ),
        stable_tag="v1.0.0",
        annotated=True,
        push_remote="origin",
        create_candidate_tag=True,
        create_stable_tag=False,
    )

    plan.validate()
