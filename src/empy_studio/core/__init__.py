"""Provider-independent product core for Empy Studio."""

from .contracts import (
    AIDriver,
    DriverCapabilities,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverStatus,
    ProjectDescriptor,
    ProjectService,
    WorkspaceStore,
)

__all__ = [
    "AIDriver",
    "DriverCapabilities",
    "DriverExecutionRequest",
    "DriverExecutionResult",
    "DriverStatus",
    "ProjectDescriptor",
    "ProjectService",
    "WorkspaceStore",
    "DefaultProjectService",
    "ProjectDetection",
    "ProductTask",
    "TASK_TEMPLATES",
    "TaskKind",
    "TaskTemplate",
    "build_product_task",
    "mark_ready_for_planning",
    "split_multiline",
    "template_by_key",
    "ExecutionPlan",
    "PlanStep",
    "approve_execution_plan",
    "cancel_execution_plan",
    "generate_execution_plan",
]

from .project_service import (
    DefaultProjectService,
    ProjectDetection,
)

from .task_intake import (
    ProductTask,
    TASK_TEMPLATES,
    TaskKind,
    TaskTemplate,
    build_product_task,
    mark_ready_for_planning,
    split_multiline,
    template_by_key,
)

from .planner import (
    ExecutionPlan,
    PlanStep,
    approve_execution_plan,
    cancel_execution_plan,
    generate_execution_plan,
)
