from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def valid_task() -> dict[str, object]:
    return {
        "task_id": "ticket-5",
        "title": "Add Codex workflow adapter",
        "objective": (
            "Prepare a bounded, evidence-backed Codex run."
        ),
        "acceptance_criteria": [
            "Context is bounded",
            "Evidence is preserved",
        ],
        "allowed_paths": ["src/", "tests/"],
        "forbidden_paths": [".env"],
        "verification_commands": [
            "python -m pytest -q",
        ],
    }


def test_task_contract_round_trip() -> None:
    contract = CodexTaskContract.from_dict(valid_task())

    assert contract.task_id == "ticket-5"
    assert len(contract.acceptance_criteria) == 2
    assert contract.to_dict()["allowed_paths"] == (
        "src/",
        "tests/",
    )


def test_task_requires_acceptance_criteria() -> None:
    data = valid_task()
    data["acceptance_criteria"] = []

    with pytest.raises(
        ValueError,
        match="acceptance criterion",
    ):
        CodexTaskContract.from_dict(data)


def test_rejects_conflicting_path_rules() -> None:
    data = valid_task()
    data["forbidden_paths"] = ["src/"]

    with pytest.raises(
        ValueError,
        match="both allowed and forbidden",
    ):
        CodexTaskContract.from_dict(data)


def test_default_execution_policy_is_bounded() -> None:
    policy = CodexExecutionPolicy.from_dict({})

    assert policy.mode == "non_interactive"
    assert policy.sandbox == "workspace-write"
    assert policy.approval_policy == "never"
    assert policy.timeout_seconds == 1800


def test_non_interactive_policy_cannot_wait_for_approval() -> None:
    with pytest.raises(
        ValueError,
        match="must not wait",
    ):
        CodexExecutionPolicy.from_dict(
            {
                "mode": "non_interactive",
                "approval_policy": "on-request",
            }
        )


def test_planned_manifest_round_trip(
    tmp_path: Path,
) -> None:
    manifest = CodexRunManifest.from_dict(
        {
            "run_id": "run-001",
            "project_root": str(tmp_path.resolve()),
            "task": valid_task(),
            "policy": {},
            "status": "planned",
            "metadata": {
                "ticket": "5.1",
            },
        }
    )

    assert manifest.status == "planned"
    assert manifest.policy.sandbox == "workspace-write"
    assert manifest.metadata["ticket"] == "5.1"


def test_prepared_manifest_requires_materialized_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="missing",
    ):
        CodexRunManifest.from_dict(
            {
                "run_id": "run-002",
                "project_root": str(tmp_path.resolve()),
                "task": valid_task(),
                "policy": {},
                "status": "prepared",
            }
        )


def test_project_root_must_be_absolute() -> None:
    with pytest.raises(
        ValueError,
        match="absolute",
    ):
        CodexRunManifest.from_dict(
            {
                "run_id": "run-003",
                "project_root": "relative/project",
                "task": valid_task(),
                "policy": {},
            }
        )
