"""Measure deterministic planning overhead with and without specialist fan-out.

This benchmark never calls a provider. It compares the locked local token
allocations for the same synthetic multi-domain ticket so regressions in the
economy planner are visible before a real model is used.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
    policy_for_preset,
)


def _measure(root: Path, *, specialists: bool) -> dict[str, object]:
    project = DefaultProjectService().detect(root)
    phrase = (
        "Use separate specialist agents for frontend, backend and release."
        if specialists
        else "Keep the work bounded and economical."
    )
    task = ProductTask(
        task_id=f"token-benchmark-{'specialist' if specialists else 'economy'}",
        project_root=str(root.resolve()),
        kind="release",
        title="Update frontend backend release",
        objective=(
            "Update the frontend, backend integration and release files together. "
            + phrase
        ),
        requirements=("Keep the existing deterministic tests passing",),
        constraints=("Do not change dependencies",),
        definition_of_done=("The requested changes are verified",),
        status="ready_for_planning",
    )
    draft = generate_execution_plan(task=task, project=project)
    plan = approve_execution_plan(draft, current_task=task)
    selection = build_context_selection(task=task, project=project, plan=plan)
    budget = lock_token_budget(
        build_token_budget(
            plan=plan,
            selection=selection,
            policy=policy_for_preset("economy"),
        )
    )
    return {
        "roles": [step.suggested_agent for step in plan.steps],
        "provider_nodes": len(plan.steps),
        "estimated_context_tokens": budget.estimated_context_tokens,
        "planned_total_tokens": budget.total_limit_tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=False)

    with tempfile.TemporaryDirectory(prefix="empy-token-benchmark-") as raw_root:
        root = Path(raw_root)
        (root / "package.json").write_text(
            '{"scripts":{"test":"node test.js"}}\n',
            encoding="utf-8",
        )
        (root / "src").mkdir()
        (root / "public").mkdir()
        (root / "tests").mkdir()
        for relative in (
            "src/app.py",
            "src/api.py",
            "public/index.html",
            "tests/test_app.py",
            "README.md",
        ):
            (root / relative).write_text("bounded fixture\n", encoding="utf-8")
        economy = _measure(root, specialists=False)
        specialist = _measure(root, specialists=True)

    economy_total = int(economy["planned_total_tokens"])
    specialist_total = int(specialist["planned_total_tokens"])
    report = {
        "status": "passed" if economy_total < specialist_total else "failed",
        "provider_calls": 0,
        "economy": economy,
        "explicit_specialists": specialist,
        "planned_token_reduction": specialist_total - economy_total,
        "planned_reduction_ratio": round(
            (specialist_total - economy_total) / specialist_total, 4
        )
        if specialist_total
        else None,
        "note": (
            "Deterministic plan estimate only; no model quality, provider billing, "
            "or hidden reasoning-token savings are inferred."
        ),
    }
    (args.evidence_dir / "result.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
