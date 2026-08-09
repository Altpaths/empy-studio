from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from empy_studio.core import (
    ContextSelection,
    ExecutionPlan,
    ProductTask,
    ProjectDetection,
    TokenBudget,
    build_context_selection,
    estimate_tokens,
)
from empy_studio.core.project_brain import (
    ProjectBrainIndex,
)
from empy_studio.core.project_brain import (
    build_load_save_project_brain_index as _build_load_save_project_brain_index,
)

MAX_SAFE_FULL_CONTEXT_BYTES: Final[int] = 1_048_576
ESTIMATE_SOURCE: Final[str] = "provider_neutral_local_estimate"


def build_load_save_project_brain_index(
    *,
    project_id: str,
    project: ProjectDetection,
    path: str | Path,
) -> ProjectBrainIndex:
    """Compatibility wrapper for the first benchmark API.

    The durable index now lives in core/project_brain.py; the project ID is
    retained here so older callers can migrate without changing their call
    shape.
    """

    del project_id
    return _build_load_save_project_brain_index(
        project.descriptor.root,
        path,
    ).index


@dataclass(frozen=True)
class BenchmarkResult:
    candidate_files: tuple[str, ...]
    selected_files: tuple[str, ...]
    full_context_estimate_tokens: int
    bounded_context_estimate_tokens: int
    saved_tokens: int
    savings_percentage: float
    source_estimate: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_files": list(self.candidate_files),
            "selected_files": list(self.selected_files),
            "full_context_estimate_tokens": self.full_context_estimate_tokens,
            "bounded_context_estimate_tokens": self.bounded_context_estimate_tokens,
            "saved_tokens": self.saved_tokens,
            "savings_percentage": self.savings_percentage,
            "source_estimate": self.source_estimate,
        }


def _read_for_estimate(root: Path, relative_path: str) -> str:
    path = (root / relative_path).resolve()
    if root not in path.parents and path != root:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[:MAX_SAFE_FULL_CONTEXT_BYTES].decode("utf-8", errors="replace")


def _selected_files(selection: ContextSelection) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.relative_path
                for pack in selection.packs
                for item in pack.files
            }
        )
    )


def _estimate_full_context(
    *,
    task: ProductTask,
    project: ProjectDetection,
    plan: ExecutionPlan,
    brain_index: ProjectBrainIndex,
) -> int:
    root = project.descriptor.root
    task_text = "\n".join(
        (
            task.title,
            task.objective,
            *task.requirements,
            *task.constraints,
            *task.definition_of_done,
        )
    )
    total = 0
    for step in plan.steps:
        total += estimate_tokens(f"{task_text}\n{step.title}\n{step.objective}")
        for item in brain_index.records:
            total += estimate_tokens(item.relative_path)
            total += estimate_tokens(_read_for_estimate(root, item.relative_path))
    return total


def run_local_benchmark(
    *,
    task: ProductTask,
    project: ProjectDetection,
    plan: ExecutionPlan,
    brain_index: ProjectBrainIndex,
    selection: ContextSelection | None = None,
    budget: TokenBudget | None = None,
) -> BenchmarkResult:
    task.validate()
    project.descriptor.validate()
    plan.validate()
    bounded_selection = selection or build_context_selection(
        task=task,
        project=project,
        plan=plan,
        brain_index=brain_index,
    )
    bounded_estimate = (
        budget.estimated_context_tokens
        if budget is not None and budget.selection_id == bounded_selection.selection_id
        else sum(
            estimate_tokens(pack.objective)
            + sum(
                estimate_tokens(file.relative_path)
                + estimate_tokens(" ".join(file.reasons))
                + estimate_tokens(file.content)
                for file in pack.files
            )
            for pack in bounded_selection.packs
        )
    )
    raw_full_estimate = _estimate_full_context(
        task=task,
        project=project,
        plan=plan,
        brain_index=brain_index,
    )
    full_estimate = max(raw_full_estimate, bounded_estimate)
    saved = max(0, full_estimate - bounded_estimate)
    percentage = round((saved / full_estimate * 100.0), 2) if full_estimate else 0.0
    return BenchmarkResult(
        candidate_files=tuple(item.relative_path for item in brain_index.records),
        selected_files=_selected_files(bounded_selection),
        full_context_estimate_tokens=full_estimate,
        bounded_context_estimate_tokens=bounded_estimate,
        saved_tokens=saved,
        savings_percentage=percentage,
        source_estimate=ESTIMATE_SOURCE,
    )
