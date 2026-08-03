from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.release_manifest import (
    ReleaseManifest,
)
from empy_studio.release_tag import (
    ReleaseTagError,
    create_controlled_tag,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


def manifest() -> ReleaseManifest:
    return ReleaseManifest.create(
        product="Empy Studio",
        version=ReleaseVersion.parse(
            "1.0.0"
        ),
        release_name="Empy Studio 1.0.0",
        notes_file="RELEASE_NOTES.md",
    )


def test_creates_annotated_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(
        repository_root: Path,
        *args: str,
    ) -> str:
        calls.append(args)
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == ("tag", "--list", "v1.0.0"):
            return ""
        if args[:2] == ("tag", "-a"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(
        "empy_studio.release_tag._run_git",
        fake_git,
    )

    result = create_controlled_tag(
        manifest(),
        tmp_path,
    )

    assert result.status == "created"
    assert result.tag == "v1.0.0"
    assert any(
        call[:2] == ("tag", "-a")
        for call in calls
    )


def test_pushes_only_when_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(
        repository_root: Path,
        *args: str,
    ) -> str:
        calls.append(args)
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == ("tag", "--list", "v1.0.0"):
            return ""
        if args[:2] == ("tag", "-a"):
            return ""
        if args == (
            "push",
            "origin",
            "v1.0.0",
        ):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(
        "empy_studio.release_tag._run_git",
        fake_git,
    )

    result = create_controlled_tag(
        manifest(),
        tmp_path,
        push=True,
    )

    assert result.pushed is True
    assert (
        "push",
        "origin",
        "v1.0.0",
    ) in calls


def test_rejects_wrong_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "empy_studio.release_tag._run_git",
        lambda root, *args: (
            "feature/release-manager"
            if args
            == ("branch", "--show-current")
            else ""
        ),
    )

    with pytest.raises(
        ReleaseTagError,
        match="current branch",
    ):
        create_controlled_tag(
            manifest(),
            tmp_path,
        )
