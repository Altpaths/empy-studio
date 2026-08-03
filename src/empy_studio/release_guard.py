from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .artifact_index import ArtifactIndex, verify_artifact_index
from .release_manifest import ReleaseManifest


class ReleaseGuardError(RuntimeError):
    pass


class ReleaseRollbackError(RuntimeError):
    pass


class ReleaseControlTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class ReleaseGuardResult:
    status: str
    repository: str
    branch: str
    commit_sha: str
    workflow_name: str
    workflow_run_id: int
    workflow_conclusion: str
    tag: str
    checks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RollbackMetadata:
    schema_version: int
    repository: str
    release_id: int
    tag: str
    version: str
    commit_sha: str
    previous_version: str | None
    previous_tag: str | None
    reason: str
    deleted_release: bool
    deleted_tag: bool
    artifact_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, destination: str | Path) -> Path:
        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
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
        raise ReleaseGuardError(
            f"Git command failed: git {' '.join(args)}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def verify_local_release_state(
    manifest: ReleaseManifest,
    artifact_index: ArtifactIndex,
    repository_root: str | Path,
    *,
    expected_branch: str = "main",
) -> tuple[str, str, tuple[str, ...]]:
    manifest.validate()
    artifact_index.validate()

    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    checks: list[str] = []

    branch = _run_git(root, "branch", "--show-current")
    if branch != expected_branch:
        raise ReleaseGuardError(
            f"Release must run from branch {expected_branch!r}; "
            f"current branch is {branch!r}"
        )
    checks.append("branch")

    status = _run_git(root, "status", "--porcelain")
    if status:
        raise ReleaseGuardError(
            "Release requires a clean Git working tree"
        )
    checks.append("clean_worktree")

    commit_sha = _run_git(root, "rev-parse", "HEAD")
    if not commit_sha:
        raise ReleaseGuardError(
            "Unable to resolve release commit SHA"
        )
    checks.append("commit_sha")

    tag_commit = _run_git(
        root,
        "rev-list",
        "-n",
        "1",
        manifest.tag,
    )
    if tag_commit != commit_sha:
        raise ReleaseGuardError(
            "Release tag does not point to HEAD"
        )
    checks.append("tag_matches_head")

    issues = verify_artifact_index(artifact_index)
    if issues:
        raise ReleaseGuardError(
            "Artifact verification failed: "
            + "; ".join(issues)
        )
    checks.append("artifacts")

    if artifact_index.version != str(manifest.version):
        raise ReleaseGuardError(
            "Artifact index version does not match manifest"
        )
    if artifact_index.tag != manifest.tag:
        raise ReleaseGuardError(
            "Artifact index tag does not match manifest"
        )
    checks.append("manifest_consistency")

    return branch, commit_sha, tuple(checks)


def verify_github_ci(
    transport: ReleaseControlTransport,
    *,
    api_url: str,
    repository: str,
    token: str,
    branch: str,
    commit_sha: str,
    workflow_name: str = "CI",
) -> tuple[int, str]:
    owner, name = repository.split("/", 1)
    url = (
        api_url.rstrip("/")
        + f"/repos/{owner}/{name}/actions/runs"
        + f"?branch={branch}&head_sha={commit_sha}"
        + "&status=completed&per_page=100"
    )

    response = transport.request_json(
        "GET",
        url,
        token=token,
    )
    if not isinstance(response, dict):
        raise ReleaseGuardError(
            "GitHub Actions response must be an object"
        )

    raw_runs = response.get("workflow_runs", [])
    if not isinstance(raw_runs, list):
        raise ReleaseGuardError(
            "GitHub Actions workflow_runs must be a list"
        )

    matching = [
        run
        for run in raw_runs
        if str(run.get("name")) == workflow_name
        and str(run.get("head_sha")) == commit_sha
    ]
    if not matching:
        raise ReleaseGuardError(
            f"No completed {workflow_name!r} workflow "
            f"was found for commit {commit_sha}"
        )

    latest = max(
        matching,
        key=lambda run: (
            str(run.get("run_started_at", "")),
            int(run.get("id", 0)),
        ),
    )

    conclusion = str(latest.get("conclusion"))
    if conclusion != "success":
        raise ReleaseGuardError(
            f"Workflow {workflow_name!r} did not succeed: "
            f"{conclusion}"
        )

    return int(latest["id"]), conclusion


def guard_release(
    manifest: ReleaseManifest,
    artifact_index: ArtifactIndex,
    *,
    repository_root: str | Path,
    repository: str,
    token: str,
    transport: ReleaseControlTransport,
    api_url: str = "https://api.github.com",
    expected_branch: str = "main",
    workflow_name: str = "CI",
) -> ReleaseGuardResult:
    if not token.strip():
        raise ValueError("GitHub token cannot be empty")

    branch, commit_sha, checks = verify_local_release_state(
        manifest,
        artifact_index,
        repository_root,
        expected_branch=expected_branch,
    )

    workflow_run_id, conclusion = verify_github_ci(
        transport,
        api_url=api_url,
        repository=repository,
        token=token,
        branch=branch,
        commit_sha=commit_sha,
        workflow_name=workflow_name,
    )

    return ReleaseGuardResult(
        status="ready",
        repository=repository,
        branch=branch,
        commit_sha=commit_sha,
        workflow_name=workflow_name,
        workflow_run_id=workflow_run_id,
        workflow_conclusion=conclusion,
        tag=manifest.tag,
        checks=(*checks, "ci_success"),
    )


def rollback_failed_release(
    transport: ReleaseControlTransport,
    *,
    api_url: str,
    repository: str,
    token: str,
    release_id: int,
    manifest: ReleaseManifest,
    commit_sha: str,
    reason: str,
    artifact_index: ArtifactIndex,
    delete_tag: bool = True,
) -> RollbackMetadata:
    if not reason.strip():
        raise ValueError(
            "Rollback reason cannot be empty"
        )

    owner, name = repository.split("/", 1)
    release_url = (
        api_url.rstrip("/")
        + f"/repos/{owner}/{name}/releases/{release_id}"
    )

    transport.request_json(
        "DELETE",
        release_url,
        token=token,
    )
    deleted_release = True
    deleted_tag = False

    if delete_tag:
        encoded_tag = manifest.tag.replace("/", "%2F")
        tag_url = (
            api_url.rstrip("/")
            + f"/repos/{owner}/{name}/git/refs/tags/"
            + encoded_tag
        )
        transport.request_json(
            "DELETE",
            tag_url,
            token=token,
        )
        deleted_tag = True

    return RollbackMetadata(
        schema_version=1,
        repository=repository,
        release_id=release_id,
        tag=manifest.tag,
        version=str(manifest.version),
        commit_sha=commit_sha,
        previous_version=(
            str(manifest.previous_version)
            if manifest.previous_version is not None
            else None
        ),
        previous_tag=(
            f"v{manifest.previous_version}"
            if manifest.previous_version is not None
            else None
        ),
        reason=reason,
        deleted_release=deleted_release,
        deleted_tag=deleted_tag,
        artifact_names=tuple(
            entry.name
            for entry in artifact_index.entries
        ),
    )


def guarded_publish(
    publish_callable: Any,
    *,
    manifest: ReleaseManifest,
    artifact_index: ArtifactIndex,
    repository_root: str | Path,
    repository: str,
    token: str,
    transport: ReleaseControlTransport,
    rollback_dir: str | Path,
    api_url: str = "https://api.github.com",
    expected_branch: str = "main",
    workflow_name: str = "CI",
) -> Any:
    guard = guard_release(
        manifest,
        artifact_index,
        repository_root=repository_root,
        repository=repository,
        token=token,
        transport=transport,
        api_url=api_url,
        expected_branch=expected_branch,
        workflow_name=workflow_name,
    )

    try:
        return publish_callable()
    except Exception as exc:
        release_id = getattr(
            exc,
            "release_id",
            None,
        )
        if release_id is None:
            raise

        rollback = rollback_failed_release(
            transport,
            api_url=api_url,
            repository=repository,
            token=token,
            release_id=int(release_id),
            manifest=manifest,
            commit_sha=guard.commit_sha,
            reason=str(exc),
            artifact_index=artifact_index,
        )
        rollback.save(
            Path(rollback_dir)
            / f"rollback-{manifest.tag}.json"
        )
        raise ReleaseRollbackError(
            f"Release publication failed and was rolled back: {exc}"
        ) from exc
