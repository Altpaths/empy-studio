from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.core import (
    AgentTokenAllocation,
    BudgetPreset,
    BudgetStatus,
    TokenBudget,
)
from empy_studio.core.planner import AgentRole


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


class TokenBudgetWorkspaceAdapter:
    """Persist pre-execution token budgets and immutable run limits."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace_root / "token-budgets.json"

    def save_budget(self, budget: TokenBudget) -> None:
        budget.validate()
        existing = {
            str(item["budget_id"]): item
            for item in self._read()
            if "budget_id" in item
        }
        existing[budget.budget_id] = budget.to_dict()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                list(existing.values()),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get_for_selection(self, selection_id: str) -> TokenBudget | None:
        matches = [
            item
            for item in self._read()
            if item.get("selection_id") == selection_id
        ]
        if not matches:
            return None
        return self._from_dict(matches[-1])

    def list_budgets(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[TokenBudget, ...]:
        values = self._read()
        if project_root is not None:
            values = [
                item
                for item in values
                if item.get("project_root") == project_root
            ]
        return tuple(self._from_dict(item) for item in values)

    def _from_dict(self, value: dict[str, object]) -> TokenBudget:
        raw_allocations = value.get("allocations", [])
        if not isinstance(raw_allocations, list):
            raise TypeError("allocations must be a list")
        allocations: list[AgentTokenAllocation] = []
        for raw in raw_allocations:
            if not isinstance(raw, dict):
                continue
            allocations.append(
                AgentTokenAllocation(
                    step_id=str(raw["step_id"]),
                    agent_role=cast(AgentRole, str(raw["agent_role"])),
                    context_tokens=_as_int(
                        raw["context_tokens"],
                        "context_tokens",
                    ),
                    instruction_tokens=_as_int(
                        raw["instruction_tokens"],
                        "instruction_tokens",
                    ),
                    response_tokens=_as_int(
                        raw["response_tokens"],
                        "response_tokens",
                    ),
                    max_retries=_as_int(
                        raw["max_retries"],
                        "max_retries",
                    ),
                    retry_tokens_per_attempt=_as_int(
                        raw["retry_tokens_per_attempt"],
                        "retry_tokens_per_attempt",
                    ),
                    max_handoffs=_as_int(
                        raw["max_handoffs"],
                        "max_handoffs",
                    ),
                    handoff_tokens_per_event=_as_int(
                        raw["handoff_tokens_per_event"],
                        "handoff_tokens_per_event",
                    ),
                    base_limit_tokens=_as_int(
                        raw["base_limit_tokens"],
                        "base_limit_tokens",
                    ),
                    retry_limit_tokens=_as_int(
                        raw["retry_limit_tokens"],
                        "retry_limit_tokens",
                    ),
                    handoff_limit_tokens=_as_int(
                        raw["handoff_limit_tokens"],
                        "handoff_limit_tokens",
                    ),
                    total_limit_tokens=_as_int(
                        raw["total_limit_tokens"],
                        "total_limit_tokens",
                    ),
                )
            )

        raw_locked_at = value.get("locked_at")
        budget = TokenBudget(
            schema_version=_as_int(
                value["schema_version"],
                "schema_version",
            ),
            budget_id=str(value["budget_id"]),
            plan_id=str(value["plan_id"]),
            selection_id=str(value["selection_id"]),
            task_id=str(value["task_id"]),
            project_root=str(value["project_root"]),
            created_at=str(value["created_at"]),
            locked_at=(
                str(raw_locked_at)
                if raw_locked_at is not None
                else None
            ),
            status=cast(BudgetStatus, str(value["status"])),
            preset=cast(BudgetPreset, str(value["preset"])),
            planning_limit_tokens=_as_int(
                value["planning_limit_tokens"],
                "planning_limit_tokens",
            ),
            reserve_tokens=_as_int(
                value["reserve_tokens"],
                "reserve_tokens",
            ),
            total_limit_tokens=_as_int(
                value["total_limit_tokens"],
                "total_limit_tokens",
            ),
            estimated_context_tokens=_as_int(
                value["estimated_context_tokens"],
                "estimated_context_tokens",
            ),
            allocations=tuple(allocations),
        )
        budget.validate()
        return budget

    def _read(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
