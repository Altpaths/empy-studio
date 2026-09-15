from __future__ import annotations

import pytest

from empy_studio.core.recovery import RecoveryState, failure_fingerprint
from empy_studio.core.task_intake import ProductTask, split_multiline
from empy_studio.core.token_budget import PROVIDER_EXECUTION_OVERHEAD_TOKENS


def test_failure_fingerprint_ignores_restart_specific_values() -> None:
    first = (
        "Verification failed at line 42 after 2.4 seconds: "
        "/tmp/empy-run-a/1234567890; run 550e8400-e29b-41d4-a716-446655440000"
    )
    second = (
        "verification FAILED at line 9 after 8 seconds: "
        "/private/tmp/empy-run-b/9876543210; run "
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    )
    assert failure_fingerprint(first) == failure_fingerprint(second)


def test_recovery_detects_non_adjacent_failure_cycle() -> None:
    state = RecoveryState()
    assert state.record_failure("check A failed", "a", "frontend") is None
    assert state.record_failure("check B failed", "b", "frontend") is None
    assert state.record_failure("check A failed", "c", "frontend").startswith(
        "no_progress"
    )
    assert state.history[-1]["repeat_count"] == 1


def test_recovery_rejects_malformed_history() -> None:
    value = RecoveryState().to_dict()
    value["history"] = [{"fingerprint": "only-partial"}]
    restored = RecoveryState.from_dict(value)
    assert restored.status == "stopped"
    assert restored.stop_reason.startswith("invalid_state")


def test_task_intake_deduplicates_repeated_lines() -> None:
    assert split_multiline("Run tests\n- run   tests\nBuild\nbuild") == (
        "Run tests",
        "Build",
    )


def test_task_intake_rejects_oversized_objective() -> None:
    task = ProductTask(
        task_id="large",
        project_root="/tmp/project",
        kind="custom",
        title="Large request",
        objective="x" * 16_001,
        requirements=("Implement it",),
        constraints=(),
        definition_of_done=("It works",),
        status="ready_for_planning",
    )
    with pytest.raises(ValueError, match="objective"):
        task.validate()


def test_provider_overhead_is_bounded_for_economy_runs() -> None:
    assert PROVIDER_EXECUTION_OVERHEAD_TOKENS <= 24_000
