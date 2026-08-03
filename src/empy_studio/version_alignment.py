from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .release_version import ReleaseVersion

VersionSourceKind = Literal[
    "pyproject",
    "python",
    "text",
]


@dataclass(frozen=True)
class VersionSource:
    path: str
    kind: VersionSourceKind
    pattern: str
    required: bool = True

    def validate(self) -> None:
        if not self.path.strip():
            raise ValueError(
                "Version source path cannot be empty"
            )
        if self.kind not in {
            "pyproject",
            "python",
            "text",
        }:
            raise ValueError(
                f"Unsupported version source kind: {self.kind}"
            )
        if not self.pattern.strip():
            raise ValueError(
                "Version source pattern cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VersionObservation:
    path: str
    kind: VersionSourceKind
    required: bool
    exists: bool
    observed_version: str | None
    expected_version: str
    matched: bool
    sha256: str | None

    @property
    def passed(self) -> bool:
        if not self.required and not self.exists:
            return True
        return (
            self.exists
            and self.matched
            and self.sha256 is not None
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["passed"] = self.passed
        return value


@dataclass(frozen=True)
class VersionAlignmentEvidence:
    schema_version: int
    status: str
    project_root: str
    candidate_version: str
    target_version: str
    observations: tuple[VersionObservation, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported version-alignment schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported version-alignment status"
            )
        if not self.observations:
            raise ValueError(
                "Version alignment must contain observations"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_root": self.project_root,
            "candidate_version": self.candidate_version,
            "target_version": self.target_version,
            "observations": [
                item.to_dict()
                for item in self.observations
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


@dataclass(frozen=True)
class VersionAlignmentConfig:
    project_root: str
    evidence_path: str
    candidate_version: ReleaseVersion
    target_version: ReleaseVersion
    sources: tuple[VersionSource, ...]

    def validate(self) -> None:
        root = Path(
            self.project_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise NotADirectoryError(root)
        if not (
            root / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "project_root must contain pyproject.toml"
            )
        if not self.sources:
            raise ValueError(
                "Version sources cannot be empty"
            )

        candidate_pre = (
            self.candidate_version.prerelease
        )
        if (
            not candidate_pre
            or len(candidate_pre) < 2
            or str(candidate_pre[0]).lower() != "rc"
        ):
            raise ValueError(
                "candidate_version must be an rc prerelease"
            )

        target_pre = self.target_version.prerelease
        if target_pre not in (None, ()):
            raise ValueError(
                "target_version must be stable"
            )

        candidate_core = (
            self.candidate_version.major,
            self.candidate_version.minor,
            self.candidate_version.patch,
        )
        target_core = (
            self.target_version.major,
            self.target_version.minor,
            self.target_version.patch,
        )

        if candidate_core != target_core:
            raise ValueError(
                "Candidate and target versions must "
                "share the same core version"
            )

        for source in self.sources:
            source.validate()
            relative = Path(source.path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
            ):
                raise ValueError(
                    "Version source paths must be "
                    "safe relative paths"
                )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _extract_version(
    text: str,
    pattern: str,
) -> str | None:
    match = re.search(
        pattern,
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        return None

    try:
        return match.group("version")
    except IndexError as exc:
        raise ValueError(
            "Version source pattern must define "
            "a named group called 'version'"
        ) from exc


def run_version_alignment(
    config: VersionAlignmentConfig,
) -> VersionAlignmentEvidence:
    config.validate()

    root = Path(
        config.project_root
    ).expanduser().resolve()
    expected = str(
        config.candidate_version
    )
    observations: list[
        VersionObservation
    ] = []

    for source in config.sources:
        path = (
            root / source.path
        ).resolve()

        if (
            root not in path.parents
            and path != root
        ):
            raise ValueError(
                "Version source escapes project root"
            )

        if not path.is_file():
            observations.append(
                VersionObservation(
                    path=source.path,
                    kind=source.kind,
                    required=source.required,
                    exists=False,
                    observed_version=None,
                    expected_version=expected,
                    matched=False,
                    sha256=None,
                )
            )
            continue

        text = path.read_text(
            encoding="utf-8"
        )
        observed = _extract_version(
            text,
            source.pattern,
        )

        observations.append(
            VersionObservation(
                path=source.path,
                kind=source.kind,
                required=source.required,
                exists=True,
                observed_version=observed,
                expected_version=expected,
                matched=(observed == expected),
                sha256=_sha256(path),
            )
        )

    evidence = VersionAlignmentEvidence(
        schema_version=1,
        status=(
            "passed"
            if all(
                item.passed
                for item in observations
            )
            else "failed"
        ),
        project_root=str(root),
        candidate_version=str(
            config.candidate_version
        ),
        target_version=str(
            config.target_version
        ),
        observations=tuple(observations),
    )
    evidence.save(
        config.evidence_path
    )
    return evidence


def default_version_alignment_config(
    project_root: str | Path,
    evidence_path: str | Path,
) -> VersionAlignmentConfig:
    return VersionAlignmentConfig(
        project_root=str(project_root),
        evidence_path=str(evidence_path),
        candidate_version=ReleaseVersion.parse(
            "1.0.0-rc.1"
        ),
        target_version=ReleaseVersion.parse(
            "1.0.0"
        ),
        sources=(
            VersionSource(
                path="pyproject.toml",
                kind="pyproject",
                pattern=(
                    r'^version\s*=\s*'
                    r'["\'](?P<version>[^"\']+)["\']'
                ),
            ),
            VersionSource(
                path="src/empy_studio/__init__.py",
                kind="python",
                pattern=(
                    r'^__version__\s*=\s*'
                    r'["\'](?P<version>[^"\']+)["\']'
                ),
                required=False,
            ),
        ),
    )


def require_version_alignment(
    evidence: VersionAlignmentEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    blockers = [
        item.path
        for item in evidence.observations
        if not item.passed
    ]

    raise RuntimeError(
        "Version alignment failed: "
        + ", ".join(blockers)
    )
