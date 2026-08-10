"""Run repeatable provider-free token and timing benchmarks on fixture projects."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from empy_studio.benchmark import run_local_benchmark
from empy_studio.core import (
    DefaultProjectService,
    ProductTask,
    approve_execution_plan,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.core.project_brain import build_project_brain_index

FIXTURES: dict[str, dict[str, str]] = {
    "python": {
        "pyproject.toml": "[project]\nname = 'benchmark-python'\n",
        "src/service.py": "def run(value: str) -> str:\n    return value\n",
        "tests/test_service.py": "def test_run():\n    assert True\n",
        "README.md": "A small Python service.\n",
        "legacy/notes.txt": "legacy implementation notes with no current task relevance.\n" * 300,
    },
    "web": {
        "package.json": '{"name":"benchmark-web","version":"0.0.1"}\n',
        "src/index.ts": "export const ready = true;\n",
        "src/index.css": "body { margin: 0; }\n",
        "README.md": "A small web project.\n",
        "legacy/notes.txt": "legacy stylesheet migration notes with no current task relevance.\n" * 300,
    },
    "generic": {
        "README.md": "A generic project.\n",
        "docs/architecture.md": "## Architecture\n\nKeep modules bounded.\n",
        "src/module.txt": "module content\n",
        "legacy/notes.txt": "legacy project notes with no current task relevance.\n" * 300,
    },
}


def _run_case(name: str, files: dict[str, str]) -> dict[str, Any]:
    with TemporaryDirectory(prefix=f"empy-benchmark-{name}-") as temporary:
        root = Path(temporary)
        fixture_files = dict(files)
        for index in range(20):
            fixture_files[f"legacy/note-{index:02d}.txt"] = (
                "legacy implementation note with no current task relevance.\n" * 20
            )
        for relative, content in fixture_files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        detection = DefaultProjectService().detect(root)
        task = ProductTask(
            task_id=f"benchmark-{name}",
            project_root=str(root.resolve()),
            kind="custom",
            title=f"Benchmark {name}",
            objective="Measure bounded context selection for a repeatable fixture.",
            requirements=("Inspect the project", "Keep the benchmark provider-free"),
            constraints=("Do not change project files",),
            definition_of_done=("Produce token estimates", "Record elapsed time"),
            status="ready_for_planning",
        )
        plan = approve_execution_plan(
            generate_execution_plan(task=task, project=detection),
            current_task=task,
        )
        brain = build_project_brain_index(root).index
        selection = build_context_selection(
            task=task,
            project=detection,
            plan=plan,
            brain_index=brain,
        )
        budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
        started = time.perf_counter()
        result = run_local_benchmark(
            task=task,
            project=detection,
            plan=plan,
            brain_index=brain,
            selection=selection,
            budget=budget,
        )
        elapsed = round(time.perf_counter() - started, 6)
        return {
            "name": name,
            "elapsed_seconds": elapsed,
            "candidate_file_count": len(result.candidate_files),
            "selected_file_count": len(result.selected_files),
            "full_context_estimate_tokens": result.full_context_estimate_tokens,
            "bounded_context_estimate_tokens": result.bounded_context_estimate_tokens,
            "saved_tokens": result.saved_tokens,
            "savings_percentage": result.savings_percentage,
            "source": result.source_estimate,
        }


def run_benchmarks(
    *,
    max_seconds: float,
    min_savings_percentage: float,
) -> dict[str, Any]:
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    if min_savings_percentage < 0:
        raise ValueError("min_savings_percentage cannot be negative")
    cases = [_run_case(name, files) for name, files in FIXTURES.items()]
    failures = [
        f"{item['name']}: elapsed_seconds={item['elapsed_seconds']} > {max_seconds}"
        for item in cases
        if item["elapsed_seconds"] > max_seconds
    ]
    failures.extend(
        f"{item['name']}: savings_percentage={item['savings_percentage']} < "
        f"{min_savings_percentage}"
        for item in cases
        if item["savings_percentage"] < min_savings_percentage
    )
    return {
        "schema_version": 1,
        "status": "passed" if not failures else "failed",
        "source": "provider_neutral_local_estimate",
        "thresholds": {
            "max_seconds": max_seconds,
            "min_savings_percentage": min_savings_percentage,
        },
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "max_elapsed_seconds": max(
                (item["elapsed_seconds"] for item in cases),
                default=0,
            ),
            "min_savings_percentage": min(
                (item["savings_percentage"] for item in cases),
                default=0,
            ),
            "failures": failures,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seconds", type=float, default=5.0)
    parser.add_argument("--min-savings-percentage", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmarks(
        max_seconds=args.max_seconds,
        min_savings_percentage=args.min_savings_percentage,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
