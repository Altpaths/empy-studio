from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .release_version import ReleaseVersion


@dataclass(frozen=True)
class ControlledTagPlan:
    schema_version: int
    repository_root: str
    branch: str
    commit_sha: str
    candidate_version: ReleaseVersion
    candidate_tag: str
    stable_version: ReleaseVersion
    stable_tag: str
    annotated: bool
    push_remote: str
    create_candidate_tag: bool
    create_stable_tag: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported tag-plan schema"
            )
        if not self.repository_root.strip():
            raise ValueError(
                "repository_root cannot be empty"
            )
        if not self.branch.strip():
            raise ValueError(
                "branch cannot be empty"
            )
        if len(self.commit_sha) < 7:
            raise ValueError(
                "commit_sha is too short"
            )
        if self.candidate_tag != (
            f"v{self.candidate_version}"
        ):
            raise ValueError(
                "candidate_tag must match candidate_version"
            )
        if self.stable_tag != (
            f"v{self.stable_version}"
        ):
            raise ValueError(
                "stable_tag must match stable_version"
            )
        if not self.annotated:
            raise ValueError(
                "Release tags must be annotated"
            )
        if not self.push_remote.strip():
            raise ValueError(
                "push_remote cannot be empty"
            )
        if self.create_stable_tag:
            raise ValueError(
                "Stable tag must not be created "
                "during Release Candidate preparation"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "candidate_version": str(
                self.candidate_version
            ),
            "stable_version": str(
                self.stable_version
            ),
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
