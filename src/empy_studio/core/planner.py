from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .project_service import ProjectDetection
from .task_intake import ProductTask

PlanStatus = Literal[
    "draft",
    "approved",
    "cancelled",
]
RiskLevel = Literal[
    "low",
    "medium",
    "high",
]
AgentRole = Literal[
    "discovery",
    "frontend",
    "backend",
    "quality",
    "security",
    "release",
]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    title: str
    objective: str
    depends_on: tuple[str, ...]
    suggested_agent: AgentRole
    estimated_files: int
    risk: RiskLevel

    def validate(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id cannot be empty")
        if not self.title.strip():
            raise ValueError("step title cannot be empty")
        if not self.objective.strip():
            raise ValueError("step objective cannot be empty")
        if self.estimated_files < 0:
            raise ValueError(
                "estimated_files cannot be negative"
            )
        if self.risk not in {
            "low",
            "medium",
            "high",
        }:
            raise ValueError(
                f"unsupported risk: {self.risk}"
            )


@dataclass(frozen=True)
class ExecutionPlan:
    schema_version: int
    plan_id: str
    task_id: str
    project_root: str
    project_type: str
    status: PlanStatus
    created_at: str
    approved_at: str | None
    summary: str
    risk: RiskLevel
    estimated_files: int
    estimated_agents: int
    estimated_tokens: int
    likely_paths: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    task_fingerprint: str

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "unsupported execution-plan schema"
            )
        if not self.plan_id.strip():
            raise ValueError("plan_id cannot be empty")
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if self.status not in {
            "draft",
            "approved",
            "cancelled",
        }:
            raise ValueError(
                f"unsupported plan status: {self.status}"
            )
        if self.estimated_files < 0:
            raise ValueError(
                "estimated_files cannot be negative"
            )
        if self.estimated_agents < 1:
            raise ValueError(
                "estimated_agents must be positive"
            )
        if self.estimated_tokens < 1:
            raise ValueError(
                "estimated_tokens must be positive"
            )
        if not self.steps:
            raise ValueError(
                "execution plan must contain steps"
            )

        known = {
            step.step_id
            for step in self.steps
        }
        if len(known) != len(self.steps):
            raise ValueError(
                "plan step IDs must be unique"
            )

        for step in self.steps:
            step.validate()
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(
                    "step contains unknown dependency"
                )

        if (
            self.status == "approved"
            and self.approved_at is None
        ):
            raise ValueError(
                "approved plan requires approved_at"
            )

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["steps"] = [
            asdict(step)
            for step in self.steps
        ]
        return value


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _fingerprint_task(
    task: ProductTask,
) -> str:
    payload = json.dumps(
        asdict(task),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _likely_paths(
    task: ProductTask,
    project: ProjectDetection,
) -> tuple[str, ...]:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    ).lower()
    project_type = (
        project.descriptor.project_type
    )

    paths: list[str] = []

    if project_type == "laravel":
        if any(
            word in text
            for word in (
                "ui",
                "homepage",
                "page",
                "font",
                "image",
                "design",
                "layout",
                "rtl",
            )
        ):
            paths.extend(
                (
                    "resources/views/",
                    "resources/css/",
                    "resources/js/",
                    "public/",
                )
            )
        if any(
            word in text
            for word in (
                "route",
                "controller",
                "api",
                "backend",
                "store",
                "database",
            )
        ):
            paths.extend(
                (
                    "routes/",
                    "app/Http/",
                    "app/Models/",
                    "database/",
                )
            )
        paths.append("tests/")

    elif project_type == "python" or project_type == "node" or project_type == "rust":
        paths.extend(("src/", "tests/"))
    elif project_type == "php":
        paths.extend(("src/", "app/", "public/", "routes/", "tests/"))
    elif project_type == "go":
        paths.extend(("./",))
    else:
        paths.extend(("./",))

    return tuple(dict.fromkeys(paths))


def _risk(
    task: ProductTask,
    likely_paths: tuple[str, ...],
) -> RiskLevel:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    ).lower()

    high_terms = (
        "database migration",
        "authentication",
        "payment",
        "security",
        "delete",
        "production",
        "deployment",
    )
    medium_terms = (
        "backend",
        "api",
        "route",
        "controller",
        "integration",
        "refactor",
    )

    if any(term in text for term in high_terms):
        return "high"
    if (
        any(term in text for term in medium_terms)
        or len(likely_paths) > 5
        or len(task.requirements) > 8
    ):
        return "medium"
    return "low"


def _roles(
    task: ProductTask,
    risk: RiskLevel,
) -> tuple[AgentRole, ...]:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    ).lower()

    roles: list[AgentRole] = ["discovery"]

    if any(
        term in text
        for term in (
            "ui",
            "page",
            "font",
            "image",
            "layout",
            "css",
            "frontend",
        )
    ):
        roles.append("frontend")

    if any(
        term in text
        for term in (
            "backend",
            "api",
            "route",
            "controller",
            "database",
            "model",
        )
    ):
        roles.append("backend")

    if any(
        term in text
        for term in (
            "security",
            "permission",
            "authentication",
        )
    ):
        roles.append("security")

    if task.kind == "release":
        roles.append("release")

    # Natural-language custom tickets do not always contain a domain word
    # such as "backend" or "frontend".  Without a fallback, an actionable
    # ticket like "change the greeting and update its test" was reduced to
    # discovery + quality, so no agent could own a file.  Keep explicit
    # read-only/audit requests read-only, but route clear implementation
    # language to the backend writer as the generic code owner.  More
    # specific frontend/security/release roles above still win ownership by
    # their narrower patterns.
    implementation_terms = (
        "add",
        "change",
        "create",
        "delete",
        "fix",
        "implement",
        "modify",
        "refactor",
        "remove",
        "update",
        "write",
        "افزود",
        "تغییر",
        "اصلاح",
        "حذف",
        "ساخت",
        "پیاده",
        "رفع",
        "به‌روزرسان",
        "بروزرسان",
        "نوشتن",
    )
    if not set(roles) & {"frontend", "backend", "security", "release"} and (
        task.kind in {"bug_fix", "feature", "ui_improvement"}
        or any(term in text for term in implementation_terms)
    ):
        roles.append("backend")

    roles.append("quality")
    return tuple(dict.fromkeys(roles))


def _build_steps(
    task: ProductTask,
    roles: tuple[AgentRole, ...],
    risk: RiskLevel,
    estimated_files: int,
) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = [
        PlanStep(
            step_id="discovery",
            title="Discover relevant project scope",
            objective=(
                "Locate only the files and modules "
                "required by this task."
            ),
            depends_on=(),
            suggested_agent="discovery",
            estimated_files=max(
                1,
                estimated_files // 2,
            ),
            risk="low",
        )
    ]

    previous = "discovery"
    implementation_roles = tuple(
        role
        for role in roles
        if role not in {
            "discovery",
            "quality",
        }
    )

    for role in implementation_roles:
        step_id = f"implement-{role}"
        steps.append(
            PlanStep(
                step_id=step_id,
                title=(
                    f"Implement {role} scope"
                ),
                objective=(
                    "Apply only the approved "
                    f"{role} changes."
                ),
                depends_on=(previous,),
                suggested_agent=role,
                estimated_files=max(
                    1,
                    estimated_files
                    // max(
                        1,
                        len(implementation_roles),
                    ),
                ),
                risk=risk,
            )
        )
        previous = step_id

    steps.append(
        PlanStep(
            step_id="quality",
            title="Verify requested work",
            objective=(
                "Run relevant checks and collect "
                "evidence without publishing."
            ),
            depends_on=(previous,),
            suggested_agent="quality",
            estimated_files=0,
            risk="low",
        )
    )
    return tuple(steps)


def generate_execution_plan(
    *,
    task: ProductTask,
    project: ProjectDetection,
) -> ExecutionPlan:
    task.validate()
    project.descriptor.validate()

    if task.status != "ready_for_planning":
        raise ValueError(
            "task must be ready_for_planning"
        )

    if (
        Path(task.project_root)
        .expanduser()
        .resolve()
        != project.descriptor.root
    ):
        raise ValueError(
            "task and project roots do not match"
        )

    likely_paths = _likely_paths(
        task,
        project,
    )
    risk = _risk(task, likely_paths)
    roles = _roles(task, risk)

    base_files = (
        len(task.requirements)
        + len(likely_paths)
    )
    estimated_files = max(
        1,
        min(
            30,
            base_files,
        ),
    )
    estimated_tokens = max(
        4_000,
        min(
            120_000,
            (
                3_000
                + len(task.objective) * 8
                + sum(
                    len(item) * 8
                    for item in task.requirements
                )
                + estimated_files * 1_500
                + len(roles) * 2_000
            ),
        ),
    )
    steps = _build_steps(
        task,
        roles,
        risk,
        estimated_files,
    )

    fingerprint = _fingerprint_task(task)
    plan_id = hashlib.sha256(
        (
            task.task_id
            + fingerprint
            + project.descriptor.project_type
        ).encode("utf-8")
    ).hexdigest()[:20]

    plan = ExecutionPlan(
        schema_version=1,
        plan_id=plan_id,
        task_id=task.task_id,
        project_root=str(
            project.descriptor.root
        ),
        project_type=(
            project.descriptor.project_type
        ),
        status="draft",
        created_at=_utc_now(),
        approved_at=None,
        summary=(
            f"{len(steps)} planned steps "
            f"using {len(roles)} suggested roles"
        ),
        risk=risk,
        estimated_files=estimated_files,
        estimated_agents=len(roles),
        estimated_tokens=estimated_tokens,
        likely_paths=likely_paths,
        steps=steps,
        task_fingerprint=fingerprint,
    )
    plan.validate()
    return plan


def approve_execution_plan(
    plan: ExecutionPlan,
    *,
    current_task: ProductTask,
) -> ExecutionPlan:
    plan.validate()
    current_task.validate()

    if plan.status != "draft":
        raise ValueError(
            "only a draft plan can be approved"
        )
    if (
        _fingerprint_task(current_task)
        != plan.task_fingerprint
    ):
        raise ValueError(
            "task changed after plan generation"
        )

    approved = replace(
        plan,
        status="approved",
        approved_at=_utc_now(),
    )
    approved.validate()
    return approved


def cancel_execution_plan(
    plan: ExecutionPlan,
) -> ExecutionPlan:
    plan.validate()
    if plan.status == "approved":
        raise ValueError(
            "approved plans are immutable"
        )
    cancelled = replace(
        plan,
        status="cancelled",
    )
    cancelled.validate()
    return cancelled
