from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.release_candidate import (
    ReleaseCandidate,
    ReleaseCandidateEvidence,
    ReleaseCandidateGate,
    default_release_gates,
    require_release_ready,
)
from empy_studio.release_version import (
    ReleaseVersion,
)


def candidate() -> ReleaseCandidate:
    return ReleaseCandidate.create(
        product="Empy Studio",
        candidate_version=ReleaseVersion.parse(
            "1.0.0-rc.1"
        ),
        target_version=ReleaseVersion.parse(
            "1.0.0"
        ),
        branch="release/v1.0.0-rc",
    )


def test_creates_blocked_candidate() -> None:
    value = candidate()

    assert value.decision == "blocked"
    assert len(value.pending_gates) == 13
    assert value.failed_gates == ()


def test_default_gates_cover_release_scope() -> None:
    names = {
        gate.name
        for gate in default_release_gates()
    }

    assert names == {
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
    }


def test_updates_gate_with_evidence() -> None:
    value = candidate()

    updated = value.with_gate(
        ReleaseCandidateGate(
            name="quality_gate",
            required=True,
            status="passed",
            summary=(
                "Ruff, MyPy, and Pytest passed"
            ),
            evidence=(
                ReleaseCandidateEvidence(
                    kind="quality-report",
                    path="evidence/quality.json",
                    sha256="a" * 64,
                ),
            ),
        )
    )

    gate = next(
        item
        for item in updated.gates
        if item.name == "quality_gate"
    )
    assert gate.status == "passed"
    assert gate.evidence[0].sha256 == (
        "a" * 64
    )


def test_ready_only_after_all_required_pass(
) -> None:
    value = candidate()

    for gate in value.gates:
        value = value.with_gate(
            ReleaseCandidateGate(
                name=gate.name,
                required=True,
                status="passed",
                summary="Gate passed",
            )
        )

    assert value.decision == "ready"
    require_release_ready(value)


def test_required_gate_cannot_be_waived() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be waived",
    ):
        ReleaseCandidateGate(
            name="security_review",
            required=True,
            status="waived",
            summary="Skipped",
        ).validate()


def test_rejects_non_rc_candidate_version() -> None:
    with pytest.raises(
        ValueError,
        match="rc prerelease",
    ):
        ReleaseCandidate.create(
            product="Empy Studio",
            candidate_version=(
                ReleaseVersion.parse("1.0.0")
            ),
            target_version=(
                ReleaseVersion.parse("1.0.0")
            ),
            branch="release/v1.0.0-rc",
        )


def test_rejects_mismatched_core_versions() -> None:
    with pytest.raises(
        ValueError,
        match="same core version",
    ):
        ReleaseCandidate.create(
            product="Empy Studio",
            candidate_version=(
                ReleaseVersion.parse(
                    "1.1.0-rc.1"
                )
            ),
            target_version=(
                ReleaseVersion.parse("1.0.0")
            ),
            branch="release/v1.0.0-rc",
        )


def test_round_trip(
    tmp_path: Path,
) -> None:
    value = candidate()
    path = value.save(
        tmp_path
        / "release-candidate.json"
    )

    loaded = ReleaseCandidate.load(path)

    assert loaded == value
    assert loaded.decision == "blocked"


def test_require_ready_lists_blockers() -> None:
    with pytest.raises(
        RuntimeError,
        match="clean_environment",
    ):
        require_release_ready(
            candidate()
        )


def test_rejects_invalid_evidence_digest() -> None:
    with pytest.raises(
        ValueError,
        match="SHA-256",
    ):
        ReleaseCandidateEvidence(
            kind="report",
            path="report.json",
            sha256="bad",
        ).validate()
