from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .release_manifest import ReleaseManifest


class ReleaseTagError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseTagResult:
    status: str
    tag: str
    commit_sha: str
    repository_root: str
    pushed: bool
    remote: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_git(
    repository_root: Path,
    *args: str,
) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseTagError(
            f"Git command failed: git {' '.join(args)}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def create_controlled_tag(
    manifest: ReleaseManifest,
    repository_root: str | Path,
    *,
    expected_branch: str = "main",
    push: bool = False,
    remote: str = "origin",
) -> ReleaseTagResult:
    manifest.validate()

    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    branch = _run_git(
        root,
        "branch",
        "--show-current",
    )
    if branch != expected_branch:
        raise ReleaseTagError(
            f"Release tag must be created from "
            f"{expected_branch!r}; current branch is "
            f"{branch!r}"
        )

    status = _run_git(
        root,
        "status",
        "--porcelain",
    )
    if status:
        raise ReleaseTagError(
            "Release tag requires a clean Git working tree"
        )

    commit_sha = _run_git(
        root,
        "rev-parse",
        "HEAD",
    )

    existing = _run_git(
        root,
        "tag",
        "--list",
        manifest.tag,
    )
    if existing:
        existing_commit = _run_git(
            root,
            "rev-list",
            "-n",
            "1",
            manifest.tag,
        )
        if existing_commit != commit_sha:
            raise ReleaseTagError(
                "Existing release tag does not point to HEAD"
            )

        return ReleaseTagResult(
            status="existing",
            tag=manifest.tag,
            commit_sha=commit_sha,
            repository_root=str(root),
            pushed=False,
            remote=None,
        )

    _run_git(
        root,
        "tag",
        "-a",
        manifest.tag,
        "-m",
        manifest.release_name,
        commit_sha,
    )

    pushed = False
    pushed_remote: str | None = None

    if push:
        _run_git(
            root,
            "push",
            remote,
            manifest.tag,
        )
        pushed = True
        pushed_remote = remote

    return ReleaseTagResult(
        status="created",
        tag=manifest.tag,
        commit_sha=commit_sha,
        repository_root=str(root),
        pushed=pushed,
        remote=pushed_remote,
    )


def delete_local_tag(
    tag: str,
    repository_root: str | Path,
) -> None:
    root = Path(repository_root).expanduser().resolve()
    existing = _run_git(
        root,
        "tag",
        "--list",
        tag,
    )
    if existing:
        _run_git(root, "tag", "-d", tag)
