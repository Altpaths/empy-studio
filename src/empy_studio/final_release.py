from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .release_candidate import (
    ReleaseCandidate,
    ReleaseCandidateEvidence,
    ReleaseCandidateGate,
)


class LinkVerifier(Protocol):
    def __call__(
        self,
        url: str,
    ) -> bool:
        ...


@dataclass(frozen=True)
class EvidenceInput:
    gate_names: tuple[str, ...]
    path: str
    status_field: str = "status"
    passing_value: str = "passed"
    kind: str = "evidence"

    def validate(self) -> None:
        if not self.gate_names:
            raise ValueError(
                "Evidence input must map to at least one gate"
            )
        if not self.path.strip():
            raise ValueError(
                "Evidence input path cannot be empty"
            )
        if not self.status_field.strip():
            raise ValueError(
                "Evidence status field cannot be empty"
            )
        if not self.passing_value.strip():
            raise ValueError(
                "Evidence passing value cannot be empty"
            )
        if not self.kind.strip():
            raise ValueError(
                "Evidence kind cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DownloadVerification:
    target: str
    url: str
    verified: bool

    def validate(self) -> None:
        if not self.target.strip():
            raise ValueError(
                "Download target cannot be empty"
            )
        if not self.url.startswith(
            "https://github.com/"
        ):
            raise ValueError(
                "Download URL must point directly to GitHub"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalReleaseReport:
    schema_version: int
    status: str
    candidate_path: str
    publication_plan_path: str
    updated_candidate_path: str
    handoff_path: str
    evidence_inputs: tuple[EvidenceInput, ...]
    download_verification: tuple[
        DownloadVerification,
        ...
    ]
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported final-release report schema"
            )
        if self.status not in {
            "ready",
            "blocked",
        }:
            raise ValueError(
                "Unsupported final-release report status"
            )

        for item in self.evidence_inputs:
            item.validate()
        for download in self.download_verification:
            download.validate()

        if self.ready and self.blockers:
            raise ValueError(
                "Ready final-release report cannot have blockers"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "candidate_path": self.candidate_path,
            "publication_plan_path": (
                self.publication_plan_path
            ),
            "updated_candidate_path": (
                self.updated_candidate_path
            ),
            "handoff_path": self.handoff_path,
            "evidence_inputs": [
                item.to_dict()
                for item in self.evidence_inputs
            ],
            "download_verification": [
                item.to_dict()
                for item in self.download_verification
            ],
            "blockers": list(self.blockers),
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
class PublicationHandoff:
    schema_version: int
    status: str
    repository: str
    candidate_version: str
    target_version: str
    release_tag: str
    target_commitish: str
    release_notes_path: str
    publication_plan_path: str
    release_candidate_path: str
    assets: tuple[dict[str, Any], ...]
    website_links: tuple[dict[str, Any], ...]
    commands: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported publication-handoff schema"
            )
        if self.status not in {
            "ready",
            "blocked",
        }:
            raise ValueError(
                "Unsupported publication-handoff status"
            )
        if not self.repository.strip():
            raise ValueError(
                "Publication repository cannot be empty"
            )
        if not self.release_tag.strip():
            raise ValueError(
                "Publication release tag cannot be empty"
            )
        if len(self.target_commitish) < 7:
            raise ValueError(
                "Publication target commit is too short"
            )
        if not self.commands:
            raise ValueError(
                "Publication handoff must include commands"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "ready": self.ready,
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
class FinalReleaseConfig:
    candidate_path: str
    publication_plan_path: str
    updated_candidate_path: str
    handoff_path: str
    report_path: str
    evidence_inputs: tuple[EvidenceInput, ...]

    def validate(self) -> None:
        if not self.evidence_inputs:
            raise ValueError(
                "Final release requires evidence inputs"
            )

        for item in self.evidence_inputs:
            item.validate()

        for value in (
            self.candidate_path,
            self.publication_plan_path,
            self.updated_candidate_path,
            self.handoff_path,
            self.report_path,
        ):
            if not value.strip():
                raise ValueError(
                    "Final release paths cannot be empty"
                )


def _sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _load_json(
    source: str | Path,
) -> dict[str, Any]:
    path = Path(source).expanduser().resolve()
    value = json.loads(
        path.read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object in {path}"
        )
    return value


def _status_from_evidence(
    evidence: EvidenceInput,
) -> tuple[bool, str, str]:
    path = Path(
        evidence.path
    ).expanduser().resolve()

    if not path.is_file():
        return (
            False,
            "Evidence file is missing",
            "",
        )

    value = _load_json(path)
    observed = value.get(
        evidence.status_field
    )
    passed = (
        str(observed)
        == evidence.passing_value
    )

    summary = (
        f"{evidence.kind} "
        f"{'passed' if passed else 'failed'}"
    )

    return (
        passed,
        summary,
        _sha256(path),
    )


def _update_candidate_gate(
    candidate: ReleaseCandidate,
    *,
    gate_name: str,
    passed: bool,
    summary: str,
    evidence: EvidenceInput,
    digest: str,
) -> ReleaseCandidate:
    gate = next(
        (
            item
            for item in candidate.gates
            if item.name == gate_name
        ),
        None,
    )
    if gate is None:
        raise KeyError(
            f"Unknown Release Candidate gate: "
            f"{gate_name}"
        )

    return candidate.with_gate(
        ReleaseCandidateGate(
            name=gate.name,
            required=gate.required,
            status=(
                "passed"
                if passed
                else "failed"
            ),
            summary=summary,
            evidence=(
                ReleaseCandidateEvidence(
                    kind=evidence.kind,
                    path=str(
                        Path(evidence.path)
                        .expanduser()
                        .resolve()
                    ),
                    sha256=(
                        digest
                        if digest
                        else None
                    ),
                ),
            ),
        )
    )


def _default_link_verifier(
    url: str,
) -> bool:
    return url.startswith(
        "https://github.com/"
    ) and "/releases/download/" in url


def finalize_release_candidate(
    config: FinalReleaseConfig,
    *,
    link_verifier: LinkVerifier | None = None,
) -> FinalReleaseReport:
    config.validate()

    candidate = ReleaseCandidate.load(
        config.candidate_path
    )
    publication = _load_json(
        config.publication_plan_path
    )

    verification = (
        link_verifier
        or _default_link_verifier
    )

    blockers: list[str] = []

    for evidence in config.evidence_inputs:
        (
            passed,
            summary,
            digest,
        ) = _status_from_evidence(
            evidence
        )

        if not passed:
            blockers.extend(
                evidence.gate_names
            )

        for gate_name in evidence.gate_names:
            candidate = _update_candidate_gate(
                candidate,
                gate_name=gate_name,
                passed=passed,
                summary=summary,
                evidence=evidence,
                digest=digest,
            )

    raw_links = publication.get(
        "website_links",
        [],
    )
    if not isinstance(raw_links, list):
        raise TypeError(
            "Publication website_links must be a list"
        )

    download_results: list[
        DownloadVerification
    ] = []

    for item in raw_links:
        target = str(item["target"])
        url = str(item["direct_url"])
        verified = verification(url)

        result = DownloadVerification(
            target=target,
            url=url,
            verified=verified,
        )
        result.validate()
        download_results.append(result)

        if not verified:
            blockers.append(
                f"download:{target}"
            )

    download_gate_passed = (
        bool(download_results)
        and all(
            item.verified
            for item in download_results
        )
    )

    candidate = _update_candidate_gate(
        candidate,
        gate_name="download_verification",
        passed=download_gate_passed,
        summary=(
            "Direct GitHub download links verified"
            if download_gate_passed
            else "One or more download links failed"
        ),
        evidence=EvidenceInput(
            gate_names=(
                "download_verification",
            ),
            path=config.publication_plan_path,
            kind="publication-plan",
        ),
        digest=_sha256(
            Path(
                config.publication_plan_path
            ).expanduser().resolve()
        ),
    )

    publication_ready = (
        publication.get("status")
        == "ready"
    )
    if not publication_ready:
        blockers.append(
            "publication_plan"
        )

    candidate.save(
        config.updated_candidate_path
    )

    release = publication.get(
        "github_release"
    )
    if not isinstance(release, dict):
        raise TypeError(
            "Publication plan must contain github_release"
        )

    assets = publication.get(
        "assets",
        [],
    )
    if not isinstance(assets, list):
        raise TypeError(
            "Publication assets must be a list"
        )

    website_links = publication.get(
        "website_links",
        [],
    )
    if not isinstance(
        website_links,
        list,
    ):
        raise TypeError(
            "Publication website_links must be a list"
        )

    final_ready = (
        candidate.decision == "ready"
        and publication_ready
        and download_gate_passed
        and not blockers
    )

    handoff = PublicationHandoff(
        schema_version=1,
        status=(
            "ready"
            if final_ready
            else "blocked"
        ),
        repository=str(
            release["repository"]
        ),
        candidate_version=str(
            candidate.candidate_version
        ),
        target_version=str(
            candidate.target_version
        ),
        release_tag=str(
            release["tag"]
        ),
        target_commitish=str(
            release["target_commitish"]
        ),
        release_notes_path=str(
            release["body_path"]
        ),
        publication_plan_path=str(
            Path(
                config.publication_plan_path
            ).expanduser().resolve()
        ),
        release_candidate_path=str(
            Path(
                config.updated_candidate_path
            ).expanduser().resolve()
        ),
        assets=tuple(
            dict(item)
            for item in assets
        ),
        website_links=tuple(
            dict(item)
            for item in website_links
        ),
        commands=(
            (
                "git tag -a "
                f"{release['tag']} "
                f"{release['target_commitish']} "
                "-m \"Empy Studio Release Candidate\""
            ),
            (
                "git push origin "
                f"{release['tag']}"
            ),
            (
                "empy release publish "
                "--plan "
                f"{Path(config.handoff_path).name}"
            ),
        ),
    )
    handoff.save(
        config.handoff_path
    )

    report = FinalReleaseReport(
        schema_version=1,
        status=(
            "ready"
            if final_ready
            else "blocked"
        ),
        candidate_path=str(
            Path(config.candidate_path)
            .expanduser()
            .resolve()
        ),
        publication_plan_path=str(
            Path(
                config.publication_plan_path
            ).expanduser().resolve()
        ),
        updated_candidate_path=str(
            Path(
                config.updated_candidate_path
            ).expanduser().resolve()
        ),
        handoff_path=str(
            Path(config.handoff_path)
            .expanduser()
            .resolve()
        ),
        evidence_inputs=(
            config.evidence_inputs
        ),
        download_verification=tuple(
            download_results
        ),
        blockers=tuple(
            sorted(set(blockers))
        ),
    )
    report.save(
        config.report_path
    )
    return report


def default_final_release_config(
    *,
    release_root: str | Path,
) -> FinalReleaseConfig:
    root = Path(
        release_root
    ).expanduser().resolve()

    return FinalReleaseConfig(
        candidate_path=str(
            root / "release-candidate.json"
        ),
        publication_plan_path=str(
            root / "publication-plan.json"
        ),
        updated_candidate_path=str(
            root
            / "release-candidate-final.json"
        ),
        handoff_path=str(
            root / "publication-handoff.json"
        ),
        report_path=str(
            root / "final-release-report.json"
        ),
        evidence_inputs=(
            EvidenceInput(
                gate_names=(
                    "clean_environment",
                    "clean_install",
                ),
                path=str(
                    root
                    / "clean-environment.json"
                ),
                kind="clean-environment",
            ),
            EvidenceInput(
                gate_names=(
                    "real_project_scenario",
                ),
                path=str(
                    root
                    / "real-project-scenario.json"
                ),
                kind="real-project-scenario",
            ),
            EvidenceInput(
                gate_names=(
                    "security_review",
                    "dependency_audit",
                ),
                path=str(
                    root
                    / "security-audit.json"
                ),
                kind="security-audit",
            ),
            EvidenceInput(
                gate_names=(
                    "test_coverage",
                    "quality_gate",
                ),
                path=str(
                    root
                    / "quality-evidence.json"
                ),
                kind="quality-evidence",
            ),
            EvidenceInput(
                gate_names=(
                    "documentation_en",
                    "documentation_fa",
                    "example_project",
                ),
                path=str(
                    root
                    / "documentation-evidence.json"
                ),
                kind="documentation-evidence",
            ),
            EvidenceInput(
                gate_names=(
                    "version_alignment",
                ),
                path=str(
                    root
                    / "version-alignment.json"
                ),
                kind="version-alignment",
            ),
            EvidenceInput(
                gate_names=(
                    "release_assets",
                ),
                path=str(
                    root
                    / "release-assets.json"
                ),
                status_field="ready",
                passing_value="True",
                kind="release-assets",
            ),
        ),
    )


def require_final_release_ready(
    report: FinalReleaseReport,
) -> None:
    report.validate()

    if report.ready:
        return

    raise RuntimeError(
        "Final Release Candidate is blocked: "
        + ", ".join(report.blockers)
    )
