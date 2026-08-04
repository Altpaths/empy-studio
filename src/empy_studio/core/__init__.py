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
    "TASK_TEMPLATES",
    "AIDriver",
    "DefaultProjectService",
    "DriverCapabilities",
    "DriverExecutionRequest",
    "DriverExecutionResult",
    "DriverStatus",
    "ExecutionPlan",
    "PlanStep",
    "ProductTask",
    "ProjectDescriptor",
    "ProjectDetection",
    "ProjectService",
    "TaskKind",
    "TaskTemplate",
    "WorkspaceStore",
    "approve_execution_plan",
    "build_product_task",
    "cancel_execution_plan",
    "generate_execution_plan",
    "mark_ready_for_planning",
    "split_multiline",
    "template_by_key",
]

from .planner import (
    ExecutionPlan,
    PlanStep,
    approve_execution_plan,
    cancel_execution_plan,
    generate_execution_plan,
)
from .project_service import (
    DefaultProjectService,
    ProjectDetection,
)
from .task_intake import (
    TASK_TEMPLATES,
    ProductTask,
    TaskKind,
    TaskTemplate,
    build_product_task,
    mark_ready_for_planning,
    split_multiline,
    template_by_key,
)
