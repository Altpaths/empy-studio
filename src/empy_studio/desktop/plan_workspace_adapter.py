from __future__ import annotations

import json
from pathlib import Path

from empy_studio.core import (
    ExecutionPlan,
    PlanStep,
)


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


class PlanWorkspaceAdapter:
    """Persist draft and approved execution plans."""

    def __init__(
        self,
        workspace_root: str | Path,
    ) -> None:
        self.workspace_root = Path(
            workspace_root
        ).expanduser().resolve()
        self.workspace_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path = (
            self.workspace_root
            / "execution-plans.json"
        )

    def save_plan(
        self,
        plan: ExecutionPlan,
    ) -> None:
        plan.validate()
        existing = {
            item["plan_id"]: item
            for item in self._read()
        }
        existing[plan.plan_id] = (
            plan.to_dict()
        )
        self.path.write_text(
            json.dumps(
                list(existing.values()),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def get_for_task(
        self,
        task_id: str,
    ) -> ExecutionPlan | None:
        matches = [
            item
            for item in self._read()
            if item.get("task_id") == task_id
        ]
        if not matches:
            return None
        return self._from_dict(matches[-1])

    def list_plans(
        self,
        *,
        project_root: str | None = None,
    ) -> tuple[ExecutionPlan, ...]:
        values = self._read()
        if project_root is not None:
            values = [
                item
                for item in values
                if item.get("project_root")
                == project_root
            ]
        return tuple(
            self._from_dict(item)
            for item in values
        )

    def _from_dict(
        self,
        value: dict[str, object],
    ) -> ExecutionPlan:
        raw_steps = value.get(
            "steps",
            [],
        )
        if not isinstance(raw_steps, list):
            raw_steps = []

        plan = ExecutionPlan(
            schema_version=_as_int(
                value["schema_version"],
                "schema_version",
            ),
            plan_id=str(value["plan_id"]),
            task_id=str(value["task_id"]),
            project_root=str(
                value["project_root"]
            ),
            project_type=str(
                value["project_type"]
            ),
            status=str(
                value["status"]
            ),  # type: ignore[arg-type]
            created_at=str(
                value["created_at"]
            ),
            approved_at=(
                str(value["approved_at"])
                if value.get(
                    "approved_at"
                ) is not None
                else None
            ),
            summary=str(value["summary"]),
            risk=str(
                value["risk"]
            ),  # type: ignore[arg-type]
            estimated_files=_as_int(
                value["estimated_files"],
                "estimated_files",
            ),
            estimated_agents=_as_int(
                value["estimated_agents"],
                "estimated_agents",
            ),
            estimated_tokens=_as_int(
                value["estimated_tokens"],
                "estimated_tokens",
            ),
            likely_paths=_string_tuple(
                value.get("likely_paths")
            ),
            steps=tuple(
                PlanStep(
                    step_id=str(
                        item["step_id"]
                    ),
                    title=str(item["title"]),
                    objective=str(
                        item["objective"]
                    ),
                    depends_on=tuple(
                        str(dep)
                        for dep in item.get(
                            "depends_on",
                            [],
                        )
                    ),
                    suggested_agent=str(
                        item[
                            "suggested_agent"
                        ]
                    ),  # type: ignore[arg-type]
                    estimated_files=_as_int(
                        item["estimated_files"],
                        "step.estimated_files",
                    ),
                    risk=str(
                        item["risk"]
                    ),  # type: ignore[arg-type]
                )
                for item in raw_steps
                if isinstance(item, dict)
            ),
            task_fingerprint=str(
                value["task_fingerprint"]
            ),
        )
        plan.validate()
        return plan

    def _read(
        self,
    ) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        value = json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, dict)
        ]
