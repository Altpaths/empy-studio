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
    "ContextExclusion",
    "ContextFile",
    "ContextPack",
    "ContextPolicy",
    "ContextSelection",
    "DefaultProjectService",
    "DriverCapabilities",
    "DriverExecutionRequest",
    "DriverExecutionResult",
    "DriverStatus",
    "ExecutionPlan",
    "PlanStep",
    "ProductTask",
    "ProjectBrain",
    "ProjectDescriptor",
    "ProjectDetection",
    "ProjectService",
    "TaskKind",
    "TaskTemplate",
    "WorkspaceStore",
    "approve_execution_plan",
    "build_context_selection",
    "build_product_task",
    "cancel_execution_plan",
    "generate_execution_plan",
    "mark_ready_for_planning",
    "split_multiline",
    "template_by_key",
]

from .context_selector import (
    ContextExclusion,
    ContextFile,
    ContextPack,
    ContextPolicy,
    ContextSelection,
    ProjectBrain,
    build_context_selection,
)
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
