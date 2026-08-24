from __future__ import annotations

import hashlib
import json
import re
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

IMPLEMENTATION_TERMS: tuple[str, ...] = (
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
    "link",
    "button",
    "page",
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
    "لینک",
    "لینک‌دهی",
    "ارتباط",
    "همگام",
    "هماهنگ",
    "دکمه",
    "بساز",
    "ایجاد",
)
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
        if any(
            word in text
            for word in (
                "ui",
                "homepage",
                "page",
                "link",
                "button",
                "layout",
                "html",
                "صفحه",
                "ایندکس",
                "لینک",
                "دکمه",
                "رابط",
                "ظاهر",
                "طراحی",
                "همگام",
                "هماهنگ",
                "خانه",
            )
        ):
            # The PHP detector may use a nested public root.  The explicit
            # root scope lets the frontend writer see existing static pages
            # and, when necessary, receive a virtual ownership target for a
            # missing homepage without exposing the whole dependency tree.
            paths.append("./")
    elif project_type == "go":
        paths.extend(("./",))
    else:
        paths.extend(("./",))

    verification_root = project.effective_verification_root
    try:
        relative_root = verification_root.relative_to(project.descriptor.root).as_posix()
    except ValueError:
        relative_root = ""
    if relative_root and relative_root != ".":
        paths = [f"{relative_root}/{path.lstrip('./')}" for path in paths]
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

    if _contains_any_term(text, high_terms):
        return "high"
    if (
        _contains_any_term(text, medium_terms)
        or len(likely_paths) > 5
        or len(task.requirements) > 8
    ):
        return "medium"
    return "low"


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    """Match whole words/phrases without treating path fragments as domains."""

    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None
        for term in terms
    )


def _has_explicit_file_scope(text: str) -> bool:
    """Detect a ticket that already names concrete files to change."""

    return bool(
        re.search(
            r"(?:^|[\s(])(?:[\w.-]+/)+[\w./-]+\.[A-Za-z0-9_-]+\b",
            text,
        )
        or re.search(
            r"\b(?:readme|package|composer|pyproject|cargo|go)\.[A-Za-z0-9_-]+\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _should_skip_discovery(
    task: ProductTask,
    risk: RiskLevel,
    likely_paths: tuple[str, ...],
) -> bool:
    """Skip redundant discovery only for small, explicitly scoped tickets."""

    text = " ".join(
        (task.title, task.objective, *task.requirements)
    ).casefold()
    discovery_terms = (
        "discover",
        "inspect",
        "understand",
        "analy",
        "audit",
        "architecture",
        "review",
        "بررسی",
        "تحلیل",
        "ممیزی",
        "معماری",
        "شناخت",
    )
    return (
        risk == "low"
        and bool(likely_paths)
        and _has_explicit_file_scope(text)
        and not any(term in text for term in discovery_terms)
    )


def _roles(
    task: ProductTask,
    risk: RiskLevel,
    *,
    include_discovery: bool = True,
    include_quality: bool = True,
) -> tuple[AgentRole, ...]:
    text = " ".join(
        (
            task.title,
            task.objective,
            *task.requirements,
        )
    ).lower()

    roles: list[AgentRole] = ["discovery"] if include_discovery else []

    if _contains_any_term(
        text,
        (
            "ui",
            "page",
            "font",
            "image",
            "layout",
            "css",
            "frontend",
            "صفحه",
            "ایندکس",
            "لینک",
            "دکمه",
            "رابط",
            "ظاهر",
            "طراحی",
            "سربرگ",
            "رنگ",
            "همگام",
            "هماهنگ",
            "سایت",
            "خانه",
        )
    ):
        roles.append("frontend")

    if _contains_any_term(
        text,
        (
            "backend",
            "api",
            "route",
            "controller",
            "database",
            "model",
        )
    ):
        roles.append("backend")

    if _contains_any_term(
        text,
        (
            "security",
            "permission",
            "authentication",
            "امنیت",
            "مجوز",
            "احراز هویت",
            "دسترسی",
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
    if not set(roles) & {"frontend", "backend", "security", "release"} and (
        task.kind in {"bug_fix", "feature", "ui_improvement"}
        or _contains_any_term(text, IMPLEMENTATION_TERMS)
    ):
        roles.append("backend")

    if include_quality:
        roles.append("quality")
    return tuple(dict.fromkeys(roles))


def _has_deterministic_verification(project: ProjectDetection) -> bool:
    """Detect whether Empy can verify the project without a quality Agent."""

    root = project.effective_verification_root
    if project.descriptor.project_type == "node":
        try:
            value = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
        return isinstance(scripts, dict) and any(
            name in scripts for name in ("test", "build", "lint")
        )
    if project.descriptor.project_type == "python":
        return True
    if project.descriptor.project_type in {"php", "laravel", "rust", "go"}:
        return True
    return (root / ".empy" / "verification.json").is_file()


def _should_skip_provider_quality(
    task: ProductTask,
    project: ProjectDetection,
    risk: RiskLevel,
) -> bool:
    text = " ".join((task.title, task.objective, *task.requirements))
    return (
        risk == "low"
        and _has_explicit_file_scope(text)
        and task.kind in {"bug_fix", "feature", "ui_improvement", "custom"}
        and _has_deterministic_verification(project)
    )


def _build_steps(
    task: ProductTask,
    roles: tuple[AgentRole, ...],
    risk: RiskLevel,
    estimated_files: int,
    *,
    include_discovery: bool = True,
    include_quality: bool = True,
) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = []
    if include_discovery:
        steps.append(
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
        )

    previous: str | None = "discovery" if include_discovery else None
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
        if previous is None:
            step_dependencies: tuple[str, ...] = ()
        else:
            step_dependencies = (previous,)
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
                depends_on=step_dependencies,
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

    if include_quality:
        if previous is None:
            quality_dependencies: tuple[str, ...] = ()
        else:
            quality_dependencies = (previous,)
        steps.append(
            PlanStep(
                step_id="quality",
                title="Verify requested work",
                objective=(
                    "Run relevant checks and collect "
                    "evidence without publishing."
                ),
                depends_on=quality_dependencies,
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
    include_discovery = not _should_skip_discovery(
        task,
        risk,
        likely_paths,
    )
    include_quality = not _should_skip_provider_quality(task, project, risk)
    roles = _roles(
        task,
        risk,
        include_discovery=include_discovery,
        include_quality=include_quality,
    )

    # A PHP site can expose its public page as index.php while its visual
    # surface lives in HTML/CSS assets. A Persian ticket that says
    # "coordinate the page, links, and buttons" is an implementation request,
    # not a read-only audit. Ensure the server-side entry point has an owner
    # whenever the detected application actually has one.
    task_text = " ".join((task.title, task.objective, *task.requirements))
    implementation_requested = task.kind in {"bug_fix", "feature", "ui_improvement"} or _contains_any_term(
        task_text.casefold(), IMPLEMENTATION_TERMS
    )
    if (
        implementation_requested
        and project.descriptor.project_type in {"php", "laravel"}
        and "frontend" in roles
        and "backend" not in roles
        and (project.effective_verification_root / "index.php").is_file()
    ):
        roles_without_quality = tuple(role for role in roles if role != "quality")
        roles = (*roles_without_quality, "backend")
        if include_quality:
            roles = (*roles, "quality")

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
        include_discovery=include_discovery,
        include_quality=include_quality,
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
            f"{len(steps)} planned steps using {len(roles)} suggested roles"
            + (
                "; deterministic Verification replaces a redundant Provider quality node"
                if not include_quality
                else ""
            )
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
