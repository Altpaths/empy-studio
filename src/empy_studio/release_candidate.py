from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .release_version import ReleaseVersion

GateStatus = Literal[
    "pending",
    "passed",
    "failed",
    "waived",
]

ReleaseDecision = Literal[
    "blocked",
    "ready",
]

GateName = Literal[
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
]


@dataclass(frozen=True)
class ReleaseCandidateEvidence:
    kind: str
    path: str
    sha256: str | None = None
    notes: str | None = None

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ReleaseCandidateEvidence:
        evidence = cls(
            kind=str(data["kind"]),
            path=str(data["path"]),
            sha256=(
                str(data["sha256"])
                if data.get("sha256") is not None
                else None
            ),
            notes=(
                str(data["notes"])
                if data.get("notes") is not None
                else None
            ),
        )
        evidence.validate()
        return evidence

    def validate(self) -> None:
        if not self.kind.strip():
            raise ValueError(
                "Evidence kind cannot be empty"
            )
        if not self.path.strip():
            raise ValueError(
                "Evidence path cannot be empty"
            )
        if self.sha256 is not None:
            normalized = self.sha256.lower()
            if len(normalized) != 64 or any(
                character not in "0123456789abcdef"
                for character in normalized
            ):
                raise ValueError(
                    "Evidence SHA-256 must be a "
                    "64-character hexadecimal digest"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseCandidateGate:
    name: GateName
    required: bool
    status: GateStatus
    summary: str
    evidence: tuple[ReleaseCandidateEvidence, ...] = ()

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ReleaseCandidateGate:
        raw_evidence = data.get("evidence", [])
        if not isinstance(raw_evidence, list):
            raise TypeError(
                "Gate evidence must be a list"
            )

        gate = cls(
            name=cast(
                GateName,
                str(data["name"]),
            ),
            required=bool(data["required"]),
            status=cast(
                GateStatus,
                str(data["status"]),
            ),
            summary=str(data["summary"]),
            evidence=tuple(
                ReleaseCandidateEvidence.from_dict(item)
                for item in raw_evidence
            ),
        )
        gate.validate()
        return gate

    def validate(self) -> None:
        allowed_names: tuple[GateName, ...] = (
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
        allowed_statuses: tuple[GateStatus, ...] = (
            "pending",
            "passed",
            "failed",
            "waived",
        )

        if self.name not in allowed_names:
            raise ValueError(
                f"Unsupported release gate: {self.name}"
            )
        if self.status not in allowed_statuses:
            raise ValueError(
                f"Unsupported gate status: {self.status}"
            )
        if not self.summary.strip():
            raise ValueError(
                "Gate summary cannot be empty"
            )
        if self.required and self.status == "waived":
            raise ValueError(
                "Required release gates cannot be waived"
            )

        for item in self.evidence:
            item.validate()

    @property
    def is_satisfied(self) -> bool:
        return self.status in {
            "passed",
            "waived",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "status": self.status,
            "summary": self.summary,
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
        }


@dataclass(frozen=True)
class ReleaseCandidate:
    schema_version: int
    product: str
    candidate_version: ReleaseVersion
    target_version: ReleaseVersion
    branch: str
    commit_sha: str | None
    gates: tuple[ReleaseCandidateGate, ...]
    metadata: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        product: str,
        candidate_version: ReleaseVersion,
        target_version: ReleaseVersion,
        branch: str,
    ) -> ReleaseCandidate:
        candidate = cls(
            schema_version=1,
            product=product,
            candidate_version=candidate_version,
            target_version=target_version,
            branch=branch,
            commit_sha=None,
            gates=default_release_gates(),
            metadata={},
        )
        candidate.validate()
        return candidate

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> ReleaseCandidate:
        raw_gates = data.get("gates", [])
        if not isinstance(raw_gates, list):
            raise TypeError(
                "Release Candidate gates must be a list"
            )

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError(
                "Release Candidate metadata "
                "must be a JSON object"
            )

        candidate = cls(
            schema_version=int(
                data["schema_version"]
            ),
            product=str(data["product"]),
            candidate_version=ReleaseVersion.parse(
                str(data["candidate_version"])
            ),
            target_version=ReleaseVersion.parse(
                str(data["target_version"])
            ),
            branch=str(data["branch"]),
            commit_sha=(
                str(data["commit_sha"])
                if data.get("commit_sha") is not None
                else None
            ),
            gates=tuple(
                ReleaseCandidateGate.from_dict(item)
                for item in raw_gates
            ),
            metadata=metadata,
        )
        candidate.validate()
        return candidate

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported Release Candidate schema"
            )
        if not self.product.strip():
            raise ValueError(
                "Release Candidate product cannot be empty"
            )
        if not self.branch.strip():
            raise ValueError(
                "Release Candidate branch cannot be empty"
            )
        prerelease = self.candidate_version.prerelease
        if (
            prerelease is None
            or len(prerelease) < 2
            or str(prerelease[0]).lower() != "rc"
            or not str(prerelease[1]).isdigit()
        ):
            raise ValueError(
                "candidate_version must be an rc prerelease"
            )
        target_prerelease = self.target_version.prerelease
        if target_prerelease not in (None, ()):
            raise ValueError(
                "target_version must be stable"
            )
        if (
            self.candidate_version.major,
            self.candidate_version.minor,
            self.candidate_version.patch,
        ) != (
            self.target_version.major,
            self.target_version.minor,
            self.target_version.patch,
        ):
            raise ValueError(
                "Candidate and target versions must "
                "share the same core version"
            )

        names = [
            gate.name
            for gate in self.gates
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                "Release Candidate gate names "
                "must be unique"
            )

        for gate in self.gates:
            gate.validate()

    @property
    def decision(self) -> ReleaseDecision:
        required = [
            gate
            for gate in self.gates
            if gate.required
        ]
        if required and all(
            gate.status == "passed"
            for gate in required
        ):
            return "ready"
        return "blocked"

    @property
    def failed_gates(
        self,
    ) -> tuple[GateName, ...]:
        return tuple(
            gate.name
            for gate in self.gates
            if gate.status == "failed"
        )

    @property
    def pending_gates(
        self,
    ) -> tuple[GateName, ...]:
        return tuple(
            gate.name
            for gate in self.gates
            if gate.status == "pending"
        )

    def with_gate(
        self,
        updated_gate: ReleaseCandidateGate,
    ) -> ReleaseCandidate:
        updated_gate.validate()

        found = False
        gates: list[ReleaseCandidateGate] = []
        for gate in self.gates:
            if gate.name == updated_gate.name:
                gates.append(updated_gate)
                found = True
            else:
                gates.append(gate)

        if not found:
            raise KeyError(
                f"Unknown Release Candidate gate: "
                f"{updated_gate.name}"
            )

        candidate = ReleaseCandidate(
            schema_version=self.schema_version,
            product=self.product,
            candidate_version=(
                self.candidate_version
            ),
            target_version=self.target_version,
            branch=self.branch,
            commit_sha=self.commit_sha,
            gates=tuple(gates),
            metadata=self.metadata,
        )
        candidate.validate()
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "candidate_version": str(
                self.candidate_version
            ),
            "target_version": str(
                self.target_version
            ),
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "decision": self.decision,
            "failed_gates": list(
                self.failed_gates
            ),
            "pending_gates": list(
                self.pending_gates
            ),
            "gates": [
                gate.to_dict()
                for gate in self.gates
            ],
            "metadata": self.metadata,
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

    @classmethod
    def load(
        cls,
        source: str | Path,
    ) -> ReleaseCandidate:
        path = Path(source).expanduser().resolve()
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise TypeError(
                "Release Candidate file must "
                "contain a JSON object"
            )
        return cls.from_dict(value)


def default_release_gates(
) -> tuple[ReleaseCandidateGate, ...]:
    required_names: tuple[GateName, ...] = (
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

    return tuple(
        ReleaseCandidateGate(
            name=name,
            required=True,
            status="pending",
            summary=(
                f"Release gate {name} "
                "has not been evaluated"
            ),
        )
        for name in required_names
    )


def require_release_ready(
    candidate: ReleaseCandidate,
) -> None:
    candidate.validate()

    if candidate.decision == "ready":
        return

    blockers = [
        gate.name
        for gate in candidate.gates
        if (
            gate.required
            and gate.status != "passed"
        )
    ]
    raise RuntimeError(
        "Release Candidate is blocked: "
        + ", ".join(blockers)
    )
