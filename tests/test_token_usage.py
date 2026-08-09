from __future__ import annotations

import pytest

from empy_studio.token_usage import TokenUsage


def test_extracts_common_codex_nested_usage_shapes() -> None:
    event = {
        "type": "turn.completed",
        "response": {
            "usage": {
                "input_tokens": 120,
                "output_tokens": 45,
                "input_tokens_details": {"cached_tokens": 30},
                "total_tokens": 165,
                "provider": "codex",
            },
        },
    }

    usage = TokenUsage.extract_from_event(event)

    assert usage == TokenUsage(
        input=120,
        output=45,
        cached=30,
        total=165,
        source="provider",
        provider="codex",
    )


def test_extracts_legacy_prompt_completion_names() -> None:
    usage = TokenUsage.extract_from_event(
        {
            "type": "task_complete",
            "usage": {
                "prompt_tokens": "40",
                "completion_tokens": 9,
                "prompt_tokens_details": {"cached_tokens": "7"},
                "total_tokens": 49,
            },
        },
        default_provider="codex",
    )

    assert usage == TokenUsage(
        input=40,
        output=9,
        cached=7,
        total=49,
        source="provider",
        provider="codex",
    )


def test_missing_usage_returns_none() -> None:
    assert TokenUsage.extract_from_event({"type": "turn.completed"}) is None
    assert TokenUsage.aggregate([]) is None


def test_aggregates_and_marks_mixed_sources() -> None:
    usage = TokenUsage.aggregate(
        (
            TokenUsage(input=10, output=3, cached=4, total=13, source="provider", provider="codex"),
            TokenUsage(input=7, output=2, cached=0, total=9, source="estimate", provider="codex"),
        )
    )

    assert usage == TokenUsage(
        input=17,
        output=5,
        cached=4,
        total=22,
        source="mixed",
        provider="codex",
    )


def test_validation_rejects_negative_and_inconsistent_counts() -> None:
    with pytest.raises(ValueError):
        TokenUsage(input=-1, output=0, cached=0, total=0)
    with pytest.raises(ValueError):
        TokenUsage(input=10, output=0, cached=0, total=5)
