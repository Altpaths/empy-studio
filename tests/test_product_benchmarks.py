from __future__ import annotations

from scripts.run_product_benchmarks import run_benchmarks


def test_product_benchmarks_cover_multiple_projects_and_token_savings() -> None:
    result = run_benchmarks(max_seconds=5, min_savings_percentage=1)

    assert result["status"] == "passed"
    assert result["summary"]["case_count"] == 3
    assert result["summary"]["min_savings_percentage"] >= 1
    assert all(item["saved_tokens"] > 0 for item in result["cases"])
