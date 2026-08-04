from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

TaskKind = Literal[
    "bug_fix",
    "feature",
    "ui_improvement",
    "audit",
    "release",
    "custom",
]


@dataclass(frozen=True)
class TaskTemplate:
    key: TaskKind
    label: str
    description: str
    default_constraints: tuple[str, ...]
    default_definition_of_done: tuple[str, ...]


@dataclass(frozen=True)
class ProductTask:
    task_id: str
    project_root: str
    kind: TaskKind
    title: str
    objective: str
    requirements: tuple[str, ...]
    constraints: tuple[str, ...]
    definition_of_done: tuple[str, ...]
    status: str = "draft"

    def validate(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.project_root.strip():
            raise ValueError("project_root cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")
        if not self.requirements:
            raise ValueError("requirements cannot be empty")
        if not self.definition_of_done:
            raise ValueError(
                "definition_of_done cannot be empty"
            )
        if self.status not in {
            "draft",
            "ready_for_planning",
        }:
            raise ValueError(
                f"unsupported task status: {self.status}"
            )


TASK_TEMPLATES: tuple[TaskTemplate, ...] = (
    TaskTemplate(
        key="bug_fix",
        label="Fix a bug",
        description=(
            "Repair a reproducible defect without "
            "changing unrelated behavior."
        ),
        default_constraints=(
            "Do not change unrelated modules",
            "Preserve existing architecture",
        ),
        default_definition_of_done=(
            "The defect is no longer reproducible",
            "Relevant tests pass",
            "No regression is introduced",
        ),
    ),
    TaskTemplate(
        key="feature",
        label="Add a feature",
        description=(
            "Add a bounded capability to an existing product."
        ),
        default_constraints=(
            "Preserve existing architecture",
            "Do not remove completed functionality",
        ),
        default_definition_of_done=(
            "The requested capability is implemented",
            "Relevant tests pass",
            "Existing behavior remains stable",
        ),
    ),
    TaskTemplate(
        key="ui_improvement",
        label="Improve UI",
        description=(
            "Improve a specific interface without a full redesign."
        ),
        default_constraints=(
            "Do not redesign the whole product",
            "Do not remove unrelated sections",
            "Preserve the existing information architecture",
        ),
        default_definition_of_done=(
            "The requested UI changes are visible",
            "The interface remains usable",
            "No unrelated section is removed",
        ),
    ),
    TaskTemplate(
        key="audit",
        label="Audit project",
        description=(
            "Inspect a project and report prioritized findings."
        ),
        default_constraints=(
            "Do not modify project files",
            "Separate evidence from recommendations",
        ),
        default_definition_of_done=(
            "Findings are evidence-backed",
            "Risks are prioritized",
            "No project file is modified",
        ),
    ),
    TaskTemplate(
        key="release",
        label="Prepare release",
        description=(
            "Prepare an existing project for a bounded release."
        ),
        default_constraints=(
            "Do not publish without user approval",
            "Do not bypass failed quality gates",
        ),
        default_definition_of_done=(
            "Release assets are prepared",
            "Quality gates pass",
            "Release remains unpublished",
        ),
    ),
    TaskTemplate(
        key="custom",
        label="Custom task",
        description=(
            "Define a project task in natural language."
        ),
        default_constraints=(),
        default_definition_of_done=(
            "Requested work is completed",
            "Relevant verification passes",
        ),
    ),
)


def template_by_key(
    key: TaskKind,
) -> TaskTemplate:
    for template in TASK_TEMPLATES:
        if template.key == key:
            return template
    raise KeyError(key)


def split_multiline(
    value: str,
) -> tuple[str, ...]:
    return tuple(
        line.strip(" -•\t")
        for line in value.splitlines()
        if line.strip(" -•\t")
    )


def build_product_task(
    *,
    task_id: str,
    project_root: str,
    kind: TaskKind,
    title: str,
    objective: str,
    requirements_text: str,
    constraints_text: str,
    definition_of_done_text: str,
) -> ProductTask:
    template = template_by_key(kind)

    requirements = split_multiline(
        requirements_text
    )
    constraints = split_multiline(
        constraints_text
    ) or template.default_constraints
    definition_of_done = split_multiline(
        definition_of_done_text
    ) or template.default_definition_of_done

    task = ProductTask(
        task_id=task_id,
        project_root=project_root,
        kind=kind,
        title=title.strip(),
        objective=objective.strip(),
        requirements=requirements,
        constraints=constraints,
        definition_of_done=definition_of_done,
    )
    task.validate()
    return task


def mark_ready_for_planning(
    task: ProductTask,
) -> ProductTask:
    task.validate()
    value = replace(
        task,
        status="ready_for_planning",
    )
    value.validate()
    return value
