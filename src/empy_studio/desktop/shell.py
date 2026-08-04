from __future__ import annotations

import tkinter as tk
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from empy_studio.core import (
    TASK_TEMPLATES,
    AgentRunGraph,
    BudgetPreset,
    ContextSelection,
    DefaultProjectService,
    DriverConfiguration,
    DriverInspection,
    DriverSettings,
    ExecutionPlan,
    ProductTask,
    ProjectDescriptor,
    ProjectDetection,
    TaskKind,
    TokenBudget,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_product_task,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
    mark_ready_for_planning,
    policy_for_preset,
    template_by_key,
)
from empy_studio.drivers import (
    CodexDriver,
    CodexGraphExecution,
    CodexGraphRuntime,
    CodexProgressEvent,
    DriverManager,
    DriverRegistry,
    default_driver_registry,
)
from empy_studio.verification_pipeline import (
    VerificationEvent,
    VerificationReport,
    VerificationRuntime,
)

from .agent_dispatcher_workspace_adapter import (
    AgentDispatcherWorkspaceAdapter,
)
from .codex_execution_controller import (
    CodexControllerFailure,
    CodexExecutionController,
)
from .codex_execution_workspace_adapter import (
    CodexExecutionWorkspaceAdapter,
)
from .context_workspace_adapter import (
    ContextWorkspaceAdapter,
)
from .driver_settings_workspace_adapter import (
    DriverSettingsWorkspaceAdapter,
)
from .plan_workspace_adapter import (
    PlanWorkspaceAdapter,
)
from .sync_workspace_adapter import SyncWorkspaceAdapter
from .task_workspace_adapter import (
    TaskWorkspaceAdapter,
)
from .token_budget_workspace_adapter import (
    TokenBudgetWorkspaceAdapter,
)
from .verification_controller import (
    VerificationController,
    VerificationControllerFailure,
)
from .verification_workspace_adapter import VerificationWorkspaceAdapter
from .workspace_adapter import (
    DesktopWorkspaceAdapter,
)


@dataclass(frozen=True)
class NavigationItem:
    key: str
    label: str
    description: str


NAVIGATION = (
    NavigationItem(
        key="home",
        label="Home",
        description="Open or resume a project.",
    ),
    NavigationItem(
        key="projects",
        label="Projects",
        description="Recent and registered projects.",
    ),
    NavigationItem(
        key="runs",
        label="Runs",
        description="Execution history and evidence.",
    ),
    NavigationItem(
        key="sync",
        label="Sync",
        description="Review sync reports and resolve file conflicts.",
    ),
    NavigationItem(
        key="verification",
        label="Verification",
        description="Run tests, build, lint, and review evidence.",
    ),
    NavigationItem(
        key="settings",
        label="Settings",
        description="Workspace and driver settings.",
    ),
)


class EmpyDesktopShell:
    """Desktop product shell through Ticket 12."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        workspace_path: str | Path | None = None,
        project_service: DefaultProjectService | None = None,
        workspace_store: DesktopWorkspaceAdapter | None = None,
        task_store: TaskWorkspaceAdapter | None = None,
        plan_store: PlanWorkspaceAdapter | None = None,
        context_store: ContextWorkspaceAdapter | None = None,
        budget_store: TokenBudgetWorkspaceAdapter | None = None,
        dispatcher_store: AgentDispatcherWorkspaceAdapter | None = None,
        execution_store: CodexExecutionWorkspaceAdapter | None = None,
        sync_store: SyncWorkspaceAdapter | None = None,
        verification_store: VerificationWorkspaceAdapter | None = None,
        verification_controller: VerificationController | None = None,
        driver_registry: DriverRegistry | None = None,
        driver_settings_store: DriverSettingsWorkspaceAdapter | None = None,
        driver_manager: DriverManager | None = None,
        codex_driver: CodexDriver | None = None,
        execution_controller: CodexExecutionController | None = None,
    ) -> None:
        self.root = root
        self.workspace_path = (
            Path(workspace_path).expanduser()
            if workspace_path is not None
            else Path.home() / ".empy-studio"
        )
        self.project_service = (
            project_service
            or DefaultProjectService()
        )
        self.workspace_store = (
            workspace_store
            or DesktopWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.task_store = (
            task_store
            or TaskWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.plan_store = (
            plan_store
            or PlanWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.context_store = (
            context_store
            or ContextWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.budget_store = (
            budget_store
            or TokenBudgetWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.dispatcher_store = (
            dispatcher_store
            or AgentDispatcherWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.execution_store = (
            execution_store
            or CodexExecutionWorkspaceAdapter(
                self.workspace_path
            )
        )
        self.sync_store = sync_store or SyncWorkspaceAdapter(self.workspace_path)
        self.verification_store = verification_store or VerificationWorkspaceAdapter(self.workspace_path)
        self.verification_controller = verification_controller or VerificationController(
            VerificationRuntime(), self.verification_store
        )
        self.driver_registry = driver_registry or default_driver_registry()
        self.driver_settings_store = (
            driver_settings_store
            or DriverSettingsWorkspaceAdapter(
                self.workspace_path,
                self.driver_registry,
            )
        )
        loaded_driver_settings = self.driver_settings_store.load()
        self.driver_manager = (
            driver_manager
            or DriverManager(
                registry=self.driver_registry,
                settings=loaded_driver_settings,
                artifact_root=self.execution_store.run_root,
            )
        )
        self._injected_codex_driver = codex_driver
        self._injected_execution_controller = execution_controller
        self.execution_controller: CodexExecutionController | None = None
        self._configure_selected_execution_controller()
        self.current_project: (
            ProjectDetection | None
        ) = None
        self.current_task: (
            ProductTask | None
        ) = None
        self.current_plan: ExecutionPlan | None = None
        self.current_context: ContextSelection | None = None
        self.current_budget: TokenBudget | None = None
        self.current_run_graph: AgentRunGraph | None = None
        self.current_codex_run: CodexGraphExecution | None = None
        self.current_sync_id: str | None = None
        self.current_verification: VerificationReport | None = None
        self.verification_views: dict[str, tk.Text] = {}
        self.verification_status_var: tk.StringVar | None = None
        self.verification_finalize_button: ttk.Button | None = None
        self.selected_conflict_id: str | None = None
        self.sync_manual_view: tk.Text | None = None
        self.codex_status_var: tk.StringVar | None = None
        self.codex_log_view: tk.Text | None = None
        self.codex_cancel_button: ttk.Button | None = None
        self.budget_preset_var: tk.StringVar | None = None
        self.driver_default_var: tk.StringVar | None = None
        self.driver_enabled_vars: dict[str, tk.BooleanVar] = {}
        self.driver_executable_vars: dict[str, tk.StringVar] = {}
        self.driver_status_labels: dict[str, ttk.Label] = {}
        self.selected_template: TaskKind = "custom"

        self._configure_window()
        self._configure_styles()
        self._build_layout()
        self.show_page("home")

    def _configure_selected_execution_controller(self) -> None:
        if self._injected_execution_controller is not None:
            self.execution_controller = self._injected_execution_controller
            return
        selected_driver = (
            self._injected_codex_driver
            if self._injected_codex_driver is not None
            else self.driver_manager.driver()
        )
        if not isinstance(selected_driver, CodexDriver):
            self.execution_controller = None
            return
        self.execution_controller = CodexExecutionController(
            runtime=CodexGraphRuntime(
                driver=selected_driver,
                run_root=self.execution_store.run_root,
            ),
            store=self.execution_store,
        )

    def _selected_driver_inspection(
        self,
        *,
        refresh: bool = False,
    ) -> DriverInspection:
        return self.driver_manager.driver().inspect(refresh=refresh)

    def _configure_window(self) -> None:
        self.root.title("Empy Studio")
        self.root.geometry("1180x760")
        self.root.minsize(940, 640)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("Empy.TFrame", background="#111827")
        style.configure("Sidebar.TFrame", background="#0B1220")
        style.configure("Content.TFrame", background="#F6F7FB")
        style.configure(
            "Title.TLabel",
            background="#F6F7FB",
            foreground="#111827",
            font=("Helvetica Neue", 26, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background="#F6F7FB",
            foreground="#4B5563",
            font=("Helvetica Neue", 13),
        )
        style.configure(
            "SidebarTitle.TLabel",
            background="#0B1220",
            foreground="#F9FAFB",
            font=("Helvetica Neue", 20, "bold"),
        )
        style.configure(
            "SidebarCaption.TLabel",
            background="#0B1220",
            foreground="#94A3B8",
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Nav.TButton",
            anchor="w",
            padding=(16, 12),
            font=("Helvetica Neue", 12),
        )
        style.configure(
            "Primary.TButton",
            padding=(18, 12),
            font=("Helvetica Neue", 12, "bold"),
        )
        style.configure(
            "Secondary.TButton",
            padding=(14, 10),
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Card.TFrame",
            background="#FFFFFF",
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "CardTitle.TLabel",
            background="#FFFFFF",
            foreground="#111827",
            font=("Helvetica Neue", 14, "bold"),
        )
        style.configure(
            "CardBody.TLabel",
            background="#FFFFFF",
            foreground="#6B7280",
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Meta.TLabel",
            background="#FFFFFF",
            foreground="#374151",
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Field.TLabel",
            background="#F6F7FB",
            foreground="#111827",
            font=("Helvetica Neue", 11, "bold"),
        )

    def _build_layout(self) -> None:
        container = ttk.Frame(
            self.root,
            style="Empy.TFrame",
        )
        container.pack(fill="both", expand=True)

        self.sidebar = ttk.Frame(
            container,
            style="Sidebar.TFrame",
            width=240,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.content = ttk.Frame(
            container,
            style="Content.TFrame",
        )
        self.content.pack(side="left", fill="both", expand=True)

        ttk.Label(
            self.sidebar,
            text="Empy Studio",
            style="SidebarTitle.TLabel",
        ).pack(anchor="w", padx=22, pady=(28, 4))
        ttk.Label(
            self.sidebar,
            text="Product workspace",
            style="SidebarCaption.TLabel",
        ).pack(anchor="w", padx=22, pady=(0, 24))

        for item in NAVIGATION:
            ttk.Button(
                self.sidebar,
                text=item.label,
                style="Nav.TButton",
                command=partial(self.show_page, item.key),
            ).pack(fill="x", padx=14, pady=4)

        ttk.Separator(self.sidebar).pack(
            fill="x",
            padx=18,
            pady=20,
        )
        ttk.Label(
            self.sidebar,
            text="Ticket 13 · Sync & Conflict Resolver",
            style="SidebarCaption.TLabel",
        ).pack(anchor="w", padx=22)

        self.page = ttk.Frame(
            self.content,
            style="Content.TFrame",
        )
        self.page.pack(
            fill="both",
            expand=True,
            padx=34,
            pady=30,
        )

    def _clear_page(self) -> None:
        for child in self.page.winfo_children():
            child.destroy()
        self.codex_status_var = None
        self.codex_log_view = None
        self.codex_cancel_button = None
        self.verification_views = {}
        self.verification_status_var = None
        self.verification_finalize_button = None

    def show_page(
        self,
        key: str,
    ) -> None:
        self._clear_page()

        if key == "home":
            self._render_home()
        elif key == "projects":
            self._render_projects()
        elif key == "runs":
            self._render_runs()
        elif key == "sync":
            self._render_sync_reports()
        elif key == "sync-detail":
            self._render_sync_detail()
        elif key == "verification":
            self._render_verification()
        elif key == "settings":
            self._render_driver_settings()
        elif key == "project-home":
            self._render_project_home()
        elif key == "task-intake":
            self._render_task_intake()
        elif key == "task-preview":
            self._render_task_preview()
        elif key == "plan-preview":
            self._render_plan_preview()
        elif key == "context-preview":
            self._render_context_preview()
        elif key == "token-budget":
            self._render_token_budget()
        elif key == "agent-run-graph":
            self._render_agent_run_graph()
        elif key == "codex-run":
            self._render_codex_run()
        else:
            raise KeyError(key)

    def choose_project(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose a software project",
            mustexist=True,
        )
        if not selected:
            return

        try:
            detection = self.project_service.detect(selected)
            self.workspace_store.save_project(
                detection.descriptor
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to open project",
                str(exc),
            )
            return

        self.current_project = detection
        self.show_page("project-home")

    def open_registered_project(
        self,
        project: ProjectDescriptor,
    ) -> None:
        try:
            self.current_project = self.project_service.detect(
                project.root
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to open project",
                str(exc),
            )
            return
        self.show_page("project-home")

    def _render_home(self) -> None:
        ttk.Label(
            self.page,
            text=(
                "Build products with less orchestration overhead."
            ),
            style="Title.TLabel",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 10))
        ttk.Label(
            self.page,
            text=(
                "Choose a project with Finder, then create "
                "a prepared or custom task."
            ),
            style="Body.TLabel",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 26))
        ttk.Button(
            self.page,
            text="Open Project",
            style="Primary.TButton",
            command=self.choose_project,
        ).pack(anchor="w", pady=(0, 28))

        projects = self.workspace_store.list_projects()
        ttk.Label(
            self.page,
            text="Recent projects",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        if not projects:
            self._empty_card(
                "No projects yet",
                "Open a project folder to begin.",
            ).pack(fill="x")
        else:
            for project in projects[:5]:
                self._project_row(project).pack(
                    fill="x",
                    pady=5,
                )

    def _render_projects(self) -> None:
        header = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        header.pack(fill="x", pady=(0, 20))
        ttk.Label(
            header,
            text="Projects",
            style="Title.TLabel",
        ).pack(side="left")
        ttk.Button(
            header,
            text="Open Project",
            style="Primary.TButton",
            command=self.choose_project,
        ).pack(side="right")

        projects = self.workspace_store.list_projects()
        if not projects:
            self._empty_card(
                "No registered projects",
                "Use Open Project to select a folder.",
            ).pack(fill="x")
            return

        for project in projects:
            self._project_row(project).pack(
                fill="x",
                pady=6,
            )

    def _render_project_home(self) -> None:
        if self.current_project is None:
            self.show_page("home")
            return

        value = self.current_project
        project = value.descriptor

        toolbar = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        toolbar.pack(fill="x", pady=(0, 20))
        ttk.Button(
            toolbar,
            text="← Projects",
            style="Secondary.TButton",
            command=lambda: self.show_page("projects"),
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text="Create Task",
            style="Primary.TButton",
            command=lambda: self.show_page("task-intake"),
        ).pack(side="right")

        ttk.Label(
            self.page,
            text=project.display_name,
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.page,
            text=str(project.root),
            style="Body.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=(0, 20))

        summary = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        summary.pack(fill="x")
        self._metadata_card(
            summary,
            "Project type",
            project.project_type,
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=(0, 8),
        )
        self._metadata_card(
            summary,
            "Package manager",
            value.package_manager or "Not detected",
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=8,
        )
        self._metadata_card(
            summary,
            "Tests",
            "Detected" if value.has_tests else "Not detected",
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=(8, 0),
        )

        tasks = self.task_store.list_tasks(
            project_root=str(project.root)
        )
        ttk.Label(
            self.page,
            text="Project tasks",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(24, 10))

        if not tasks:
            self._empty_card(
                "No tasks yet",
                "Create a prepared or custom task.",
            ).pack(fill="x")
        else:
            for task in tasks:
                self._task_row(task).pack(
                    fill="x",
                    pady=5,
                )

    def _render_task_intake(self) -> None:
        if self.current_project is None:
            self.show_page("home")
            return

        ttk.Button(
            self.page,
            text="← Project",
            style="Secondary.TButton",
            command=lambda: self.show_page("project-home"),
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(
            self.page,
            text="Create a task",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=(
                "Choose a prepared task or create a custom one. "
                "You can edit every field before saving."
            ),
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 20))

        self.template_var = tk.StringVar(
            value="custom"
        )
        template_frame = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        template_frame.pack(fill="x", pady=(0, 18))

        for template in TASK_TEMPLATES:
            ttk.Radiobutton(
                template_frame,
                text=template.label,
                variable=self.template_var,
                value=template.key,
                command=self._apply_selected_template,
            ).pack(
                side="left",
                padx=(0, 14),
            )

        form = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        form.pack(fill="both", expand=True)

        self.title_var = tk.StringVar()
        self._field_label(form, "Task title")
        ttk.Entry(
            form,
            textvariable=self.title_var,
        ).pack(fill="x", pady=(0, 12))

        self._field_label(form, "Objective")
        self.objective_text = tk.Text(
            form,
            height=3,
            wrap="word",
        )
        self.objective_text.pack(fill="x", pady=(0, 12))

        columns = ttk.Frame(
            form,
            style="Content.TFrame",
        )
        columns.pack(fill="both", expand=True)

        self.requirements_text = self._text_column(
            columns,
            "Requirements",
            "One requirement per line",
        )
        self.constraints_text = self._text_column(
            columns,
            "Constraints",
            "What must not change",
        )
        self.dod_text = self._text_column(
            columns,
            "Definition of Done",
            "How completion is verified",
        )

        ttk.Button(
            form,
            text="Preview Task",
            style="Primary.TButton",
            command=self._preview_task,
        ).pack(anchor="e", pady=(18, 0))

        self._apply_selected_template()

    def _apply_selected_template(self) -> None:
        key = self.template_var.get()
        template = template_by_key(
            key  # type: ignore[arg-type]
        )
        self.selected_template = template.key

        self._replace_text(
            self.constraints_text,
            "\n".join(template.default_constraints),
        )
        self._replace_text(
            self.dod_text,
            "\n".join(
                template.default_definition_of_done
            ),
        )

    def _preview_task(self) -> None:
        if self.current_project is None:
            return

        try:
            task = build_product_task(
                task_id=str(uuid.uuid4()),
                project_root=str(
                    self.current_project.descriptor.root
                ),
                kind=self.selected_template,
                title=self.title_var.get(),
                objective=self.objective_text.get(
                    "1.0",
                    "end",
                ),
                requirements_text=self.requirements_text.get(
                    "1.0",
                    "end",
                ),
                constraints_text=self.constraints_text.get(
                    "1.0",
                    "end",
                ),
                definition_of_done_text=self.dod_text.get(
                    "1.0",
                    "end",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Task is incomplete",
                str(exc),
            )
            return

        self.current_task = task
        self.show_page("task-preview")

    def _render_task_preview(self) -> None:
        if self.current_task is None:
            self.show_page("task-intake")
            return

        task = self.current_task
        ttk.Button(
            self.page,
            text="← Edit Task",
            style="Secondary.TButton",
            command=lambda: self.show_page("task-intake"),
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(
            self.page,
            text="Task preview",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=task.title,
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 18))

        self._preview_section(
            "Objective",
            task.objective,
        )
        self._preview_section(
            "Requirements",
            "\n".join(
                f"• {item}"
                for item in task.requirements
            ),
        )
        self._preview_section(
            "Constraints",
            "\n".join(
                f"• {item}"
                for item in task.constraints
            ) or "None",
        )
        self._preview_section(
            "Definition of Done",
            "\n".join(
                f"• {item}"
                for item in task.definition_of_done
            ),
        )

        ttk.Button(
            self.page,
            text="Save Task",
            style="Primary.TButton",
            command=self._save_task,
        ).pack(anchor="e", pady=(18, 0))

    def _save_task(self) -> None:
        if self.current_task is None:
            return

        ready = mark_ready_for_planning(
            self.current_task
        )
        self.task_store.save_task(ready)
        self.current_task = ready

        messagebox.showinfo(
            "Task saved",
            (
                "The task is saved and ready "
                "for the Planner in Ticket 7."
            ),
        )
        self.show_page("project-home")

    def _preview_section(
        self,
        title: str,
        body: str,
    ) -> None:
        card = ttk.Frame(
            self.page,
            style="Card.TFrame",
            padding=18,
        )
        card.pack(fill="x", pady=6)
        ttk.Label(
            card,
            text=title,
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            card,
            text=body,
            style="CardBody.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w")

    def _task_row(
        self,
        task: ProductTask,
    ) -> ttk.Frame:
        row = ttk.Frame(
            self.page,
            style="Card.TFrame",
            padding=16,
        )
        text = ttk.Frame(
            row,
            style="Card.TFrame",
        )
        text.pack(
            side="left",
            fill="both",
            expand=True,
        )
        ttk.Label(
            text,
            text=task.title,
            style="CardTitle.TLabel",
        ).pack(anchor="w")

        plan = self.plan_store.get_for_task(
            task.task_id
        )
        status = (
            plan.status
            if plan is not None
            else task.status
        )
        ttk.Label(
            text,
            text=f"{task.kind} · {status}",
            style="CardBody.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        ttk.Button(
            row,
            text=(
                "View Plan"
                if plan is not None
                else "Generate Plan"
            ),
            style="Secondary.TButton",
            command=partial(self._open_task_plan, task),
        ).pack(side="right")
        return row

    def _open_task_plan(
        self,
        task: ProductTask,
    ) -> None:
        if self.current_project is None:
            return

        self.current_task = task
        existing = self.plan_store.get_for_task(
            task.task_id
        )
        if existing is not None:
            self.current_plan = existing
        else:
            try:
                generated_plan = generate_execution_plan(
                    task=task,
                    project=self.current_project,
                )
                self.plan_store.save_plan(
                    generated_plan
                )
                self.current_plan = generated_plan
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(
                    "Unable to generate plan",
                    str(exc),
                )
                return

        self.show_page("plan-preview")

    def _render_plan_preview(self) -> None:
        if (
            self.current_plan is None
            or self.current_task is None
        ):
            self.show_page("project-home")
            return

        plan = self.current_plan
        task = self.current_task

        ttk.Button(
            self.page,
            text="← Project",
            style="Secondary.TButton",
            command=lambda: self.show_page(
                "project-home"
            ),
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(
            self.page,
            text="Execution plan",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=task.title,
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 18))

        summary = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        summary.pack(fill="x")

        self._metadata_card(
            summary,
            "Risk",
            plan.risk,
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=(0, 6),
        )
        self._metadata_card(
            summary,
            "Estimated files",
            str(plan.estimated_files),
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=6,
        )
        self._metadata_card(
            summary,
            "Suggested agents",
            str(plan.estimated_agents),
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=6,
        )
        self._metadata_card(
            summary,
            "Estimated tokens",
            f"{plan.estimated_tokens:,}",
        ).pack(
            side="left",
            fill="both",
            expand=True,
            padx=(6, 0),
        )

        paths = ttk.Frame(
            self.page,
            style="Card.TFrame",
            padding=16,
        )
        paths.pack(fill="x", pady=(16, 12))
        ttk.Label(
            paths,
            text="Likely project scope",
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            paths,
            text=(
                ", ".join(plan.likely_paths)
                or "To be discovered"
            ),
            style="CardBody.TLabel",
            wraplength=780,
        ).pack(anchor="w")

        ttk.Label(
            self.page,
            text="Planned steps",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(8, 8))

        for index, step in enumerate(
            plan.steps,
            start=1,
        ):
            card = ttk.Frame(
                self.page,
                style="Card.TFrame",
                padding=14,
            )
            card.pack(fill="x", pady=4)
            ttk.Label(
                card,
                text=(
                    f"{index}. {step.title}"
                ),
                style="CardTitle.TLabel",
            ).pack(anchor="w")
            ttk.Label(
                card,
                text=(
                    f"{step.objective}\n"
                    f"Agent: {step.suggested_agent} · "
                    f"Depends on: "
                    f"{', '.join(step.depends_on) or 'none'}"
                ),
                style="CardBody.TLabel",
                wraplength=780,
            ).pack(anchor="w", pady=(5, 0))

        actions = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        actions.pack(fill="x", pady=(18, 0))

        if plan.status == "draft":
            ttk.Button(
                actions,
                text="Edit Task",
                style="Secondary.TButton",
                command=self._edit_task_from_plan,
            ).pack(side="left")
            ttk.Button(
                actions,
                text="Approve Plan",
                style="Primary.TButton",
                command=self._approve_plan,
            ).pack(side="right")
        else:
            existing_context = self.context_store.get_for_plan(
                plan.plan_id
            )
            ttk.Label(
                actions,
                text=(
                    "Approved plan — immutable. "
                    "Context is bounded before execution."
                ),
                style="Body.TLabel",
            ).pack(side="left")
            ttk.Button(
                actions,
                text=(
                    "View Context Packs"
                    if existing_context is not None
                    else "Build Context Packs"
                ),
                style="Primary.TButton",
                command=self._build_or_open_context,
            ).pack(side="right")

    def _build_or_open_context(self) -> None:
        if (
            self.current_project is None
            or self.current_task is None
            or self.current_plan is None
        ):
            return

        existing = self.context_store.get_for_plan(
            self.current_plan.plan_id
        )
        if existing is not None:
            self.current_context = existing
            self.show_page("context-preview")
            return

        try:
            selection = build_context_selection(
                task=self.current_task,
                project=self.current_project,
                plan=self.current_plan,
            )
            self.context_store.save_selection(selection)
            self.current_context = selection
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to build context",
                str(exc),
            )
            return

        self.show_page("context-preview")

    def _render_context_preview(self) -> None:
        if (
            self.current_context is None
            and self.current_plan is not None
        ):
            self.current_context = self.context_store.get_for_plan(
                self.current_plan.plan_id
            )
        if self.current_context is None:
            self.show_page("plan-preview")
            return

        selection = self.current_context
        ttk.Button(
            self.page,
            text="← Execution Plan",
            style="Secondary.TButton",
            command=partial(self.show_page, "plan-preview"),
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(
            self.page,
            text="Context packs",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=selection.project_brain.summary,
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 14))

        summary = ttk.Frame(self.page, style="Content.TFrame")
        summary.pack(fill="x", pady=(0, 14))
        self._metadata_card(
            summary,
            "Scanned candidates",
            str(selection.scanned_candidates),
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._metadata_card(
            summary,
            "Selected files",
            str(selection.selected_files),
        ).pack(side="left", fill="both", expand=True, padx=6)
        self._metadata_card(
            summary,
            "Selected bytes",
            f"{selection.selected_bytes:,}",
        ).pack(side="left", fill="both", expand=True, padx=6)
        protected_count = sum(
            1 for item in selection.exclusions if item.protected
        )
        self._metadata_card(
            summary,
            "Protected paths",
            str(protected_count),
        ).pack(side="left", fill="both", expand=True, padx=(6, 0))

        notebook = ttk.Notebook(self.page)
        notebook.pack(fill="both", expand=True)

        for pack in selection.packs:
            tab = ttk.Frame(notebook, style="Content.TFrame", padding=12)
            notebook.add(tab, text=f"{pack.agent_role}: {pack.step_id}")
            ttk.Label(
                tab,
                text=(
                    f"{pack.objective}\n"
                    f"{len(pack.files)} files · {pack.total_bytes:,} bytes "
                    f"from {pack.candidate_count} relevant candidates"
                ),
                style="Body.TLabel",
                wraplength=760,
            ).pack(anchor="w", pady=(0, 8))
            viewer = tk.Text(
                tab,
                wrap="none",
                borderwidth=1,
                relief="solid",
                font=("Menlo", 11),
            )
            viewer.pack(fill="both", expand=True)
            for item in pack.files:
                viewer.insert(
                    "end",
                    (
                        f"FILE: {item.relative_path}\n"
                        f"Score: {item.score}\n"
                        f"Reason: {', '.join(item.reasons)}\n"
                        f"Included: {item.included_bytes:,}/{item.size_bytes:,} bytes"
                        f"{' (truncated)' if item.truncated else ''}\n"
                        f"SHA256: {item.sha256}\n"
                        "----------------------------------------\n"
                        f"{item.content}\n"
                        "========================================\n\n"
                    ),
                )
            if not pack.files:
                viewer.insert(
                    "end",
                    "No readable file met the bounded relevance rules for this step.",
                )
            viewer.configure(state="disabled")

        protected_tab = ttk.Frame(
            notebook,
            style="Content.TFrame",
            padding=12,
        )
        notebook.add(protected_tab, text="Exclusions")
        exclusions_view = tk.Text(
            protected_tab,
            wrap="word",
            borderwidth=1,
            relief="solid",
            font=("Menlo", 11),
        )
        exclusions_view.pack(fill="both", expand=True)
        for exclusion in selection.exclusions:
            flag = (
                "PROTECTED"
                if exclusion.protected
                else "SKIPPED"
            )
            exclusions_view.insert(
                "end",
                (
                    f"[{flag}] {exclusion.relative_path}"
                    f" — {exclusion.reason}\n"
                ),
            )
        if not selection.exclusions:
            exclusions_view.insert("end", "No exclusions recorded.\n")
        exclusions_view.configure(state="disabled")

        budget = self.budget_store.get_for_selection(
            selection.selection_id
        )
        actions = ttk.Frame(
            self.page,
            style="Content.TFrame",
        )
        actions.pack(fill="x", pady=(12, 0))
        ttk.Label(
            actions,
            text=(
                "Context is visible and bounded. Set explicit run limits "
                "before any agent can be dispatched."
            ),
            style="Body.TLabel",
            wraplength=650,
        ).pack(side="left")
        ttk.Button(
            actions,
            text=(
                "View Token Budget"
                if budget is not None
                else "Set Token Budget"
            ),
            style="Primary.TButton",
            command=self._build_or_open_budget,
        ).pack(side="right")

    def _build_or_open_budget(self) -> None:
        if self.current_context is None or self.current_plan is None:
            return
        existing = self.budget_store.get_for_selection(
            self.current_context.selection_id
        )
        if existing is not None:
            self.current_budget = existing
            self.show_page("token-budget")
            return
        try:
            budget = build_token_budget(
                plan=self.current_plan,
                selection=self.current_context,
                policy=policy_for_preset("economy"),
            )
            self.budget_store.save_budget(budget)
            self.current_budget = budget
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to set token budget",
                str(exc),
            )
            return
        self.show_page("token-budget")

    def _render_token_budget(self) -> None:
        if (
            self.current_budget is None
            and self.current_context is not None
        ):
            self.current_budget = self.budget_store.get_for_selection(
                self.current_context.selection_id
            )
        if self.current_budget is None:
            self.show_page("context-preview")
            return

        budget = self.current_budget
        ttk.Button(
            self.page,
            text="← Context Packs",
            style="Secondary.TButton",
            command=partial(self.show_page, "context-preview"),
        ).pack(anchor="w", pady=(0, 18))
        ttk.Label(
            self.page,
            text="Token Budget Controller",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=(
                "Provider-neutral estimates define hard limits for planning, "
                "each agent step, retry attempts and handoffs."
            ),
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 14))

        summary = ttk.Frame(self.page, style="Content.TFrame")
        summary.pack(fill="x", pady=(0, 14))
        self._metadata_card(
            summary,
            "Total hard limit",
            f"{budget.total_limit_tokens:,} tokens",
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._metadata_card(
            summary,
            "Planning limit",
            f"{budget.planning_limit_tokens:,}",
        ).pack(side="left", fill="both", expand=True, padx=6)
        self._metadata_card(
            summary,
            "Context estimate",
            f"{budget.estimated_context_tokens:,}",
        ).pack(side="left", fill="both", expand=True, padx=6)
        self._metadata_card(
            summary,
            "Status",
            budget.status.upper(),
        ).pack(side="left", fill="both", expand=True, padx=(6, 0))

        controls = ttk.Frame(self.page, style="Content.TFrame")
        controls.pack(fill="x", pady=(0, 12))
        if budget.status == "draft":
            ttk.Label(
                controls,
                text="Budget preset",
                style="Field.TLabel",
            ).pack(side="left", padx=(0, 8))
            self.budget_preset_var = tk.StringVar(value=budget.preset)
            preset_box = ttk.Combobox(
                controls,
                textvariable=self.budget_preset_var,
                values=("economy", "standard", "extended"),
                state="readonly",
                width=14,
            )
            preset_box.pack(side="left")
            ttk.Button(
                controls,
                text="Recalculate",
                style="Secondary.TButton",
                command=self._rebuild_token_budget,
            ).pack(side="left", padx=8)
            ttk.Button(
                controls,
                text="Lock Run Limits",
                style="Primary.TButton",
                command=self._lock_token_budget,
            ).pack(side="right")
        else:
            ttk.Label(
                controls,
                text=(
                    f"Locked preset: {budget.preset} · "
                    f"Locked at: {budget.locked_at or 'unknown'}"
                ),
                style="Body.TLabel",
            ).pack(side="left")
            existing_graph = self.dispatcher_store.get_for_budget(
                budget.budget_id
            )
            ttk.Button(
                controls,
                text=(
                    "Open Agent Run Graph"
                    if existing_graph is not None
                    else "Build Agent Run Graph"
                ),
                style="Primary.TButton",
                command=self._build_or_open_agent_run_graph,
            ).pack(side="right")

        notebook = ttk.Notebook(self.page)
        notebook.pack(fill="both", expand=True)
        for allocation in budget.allocations:
            tab = ttk.Frame(
                notebook,
                style="Content.TFrame",
                padding=12,
            )
            notebook.add(
                tab,
                text=f"{allocation.agent_role}: {allocation.step_id}",
            )
            details = tk.Text(
                tab,
                wrap="word",
                borderwidth=1,
                relief="solid",
                font=("Menlo", 11),
                height=14,
            )
            details.pack(fill="both", expand=True)
            details.insert(
                "end",
                (
                    f"STEP: {allocation.step_id}\n"
                    f"AGENT ROLE: {allocation.agent_role}\n\n"
                    f"Context estimate: {allocation.context_tokens:,}\n"
                    f"Instruction estimate: {allocation.instruction_tokens:,}\n"
                    f"Response limit: {allocation.response_tokens:,}\n"
                    f"Base call limit: {allocation.base_limit_tokens:,}\n\n"
                    f"Retries: maximum {allocation.max_retries} · "
                    f"{allocation.retry_tokens_per_attempt:,} tokens each · "
                    f"pool {allocation.retry_limit_tokens:,}\n"
                    f"Handoffs: maximum {allocation.max_handoffs} · "
                    f"{allocation.handoff_tokens_per_event:,} tokens each · "
                    f"pool {allocation.handoff_limit_tokens:,}\n\n"
                    f"STEP HARD LIMIT: {allocation.total_limit_tokens:,} tokens\n"
                    "AUTO-STOP: exceeding the step, retry, handoff or total "
                    "limit denies further usage."
                ),
            )
            details.configure(state="disabled")

        ttk.Label(
            self.page,
            text=(
                "Budget is visible before execution. Retry and handoff counts "
                "are finite, so an infinite loop cannot be authorized. "
                "A locked budget can now be converted to an Agent Run Graph."
            ),
            style="Body.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(12, 0))

    def _rebuild_token_budget(self) -> None:
        if (
            self.current_plan is None
            or self.current_context is None
            or self.current_budget is None
            or self.current_budget.status != "draft"
            or self.budget_preset_var is None
        ):
            return
        raw_preset = self.budget_preset_var.get()
        if raw_preset not in {"economy", "standard", "extended"}:
            return
        preset = cast(BudgetPreset, raw_preset)
        try:
            budget = build_token_budget(
                plan=self.current_plan,
                selection=self.current_context,
                policy=policy_for_preset(preset),
            )
            self.budget_store.save_budget(budget)
            self.current_budget = budget
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to recalculate budget",
                str(exc),
            )
            return
        self.show_page("token-budget")

    def _lock_token_budget(self) -> None:
        if self.current_budget is None:
            return
        confirmed = messagebox.askyesno(
            "Lock run limits",
            (
                "Locked limits cannot be silently increased during a run. "
                "Continue?"
            ),
        )
        if not confirmed:
            return
        try:
            locked = lock_token_budget(self.current_budget)
            self.budget_store.save_budget(locked)
            self.current_budget = locked
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to lock token budget",
                str(exc),
            )
            return
        messagebox.showinfo(
            "Run limits locked",
            "Token limits are frozen and ready for Agent Dispatcher.",
        )
        self.show_page("token-budget")

    def _build_or_open_agent_run_graph(self) -> None:
        if (
            self.current_plan is None
            or self.current_context is None
            or self.current_budget is None
        ):
            return
        existing = self.dispatcher_store.get_for_budget(
            self.current_budget.budget_id
        )
        if existing is not None:
            self.current_run_graph = existing
            self.show_page("agent-run-graph")
            return
        try:
            graph = build_agent_run_graph(
                plan=self.current_plan,
                selection=self.current_context,
                budget=self.current_budget,
            )
            self.dispatcher_store.save_graph(graph)
            self.current_run_graph = graph
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to build Agent Run Graph",
                str(exc),
            )
            return
        self.show_page("agent-run-graph")

    def _render_agent_run_graph(self) -> None:
        if (
            self.current_run_graph is None
            and self.current_budget is not None
        ):
            self.current_run_graph = self.dispatcher_store.get_for_budget(
                self.current_budget.budget_id
            )
        if self.current_run_graph is None:
            self.show_page("token-budget")
            return

        graph = self.current_run_graph
        ttk.Button(
            self.page,
            text="← Token Budget",
            style="Secondary.TButton",
            command=partial(self.show_page, "token-budget"),
        ).pack(anchor="w", pady=(0, 18))
        ttk.Label(
            self.page,
            text="Agent Run Graph",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=(
                "Only agents required by the approved plan are assigned. "
                "Every node has bounded context, a locked token limit, "
                "single-writer file ownership, and dependency ordering."
            ),
            style="Body.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 14))

        summary = ttk.Frame(self.page, style="Content.TFrame")
        summary.pack(fill="x", pady=(0, 14))
        self._metadata_card(
            summary,
            "Assigned agents",
            str(len({node.agent_id for node in graph.nodes})),
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._metadata_card(
            summary,
            "Run nodes",
            str(len(graph.nodes)),
        ).pack(side="left", fill="both", expand=True, padx=6)
        self._metadata_card(
            summary,
            "Execution waves",
            str(len(graph.waves)),
        ).pack(side="left", fill="both", expand=True, padx=6)
        self._metadata_card(
            summary,
            "Owned files",
            str(sum(item.owner_agent_id is not None for item in graph.ownership)),
        ).pack(side="left", fill="both", expand=True, padx=(6, 0))

        run_controls = ttk.Frame(self.page, style="Content.TFrame")
        run_controls.pack(fill="x", pady=(0, 14))
        latest_run = self.execution_store.get_for_graph(graph.graph_id)
        if latest_run is not None:
            ttk.Button(
                run_controls,
                text="Open Latest Codex Run",
                style="Secondary.TButton",
                command=partial(self._open_codex_run, latest_run),
            ).pack(side="left")
        ttk.Button(
            run_controls,
            text="Run Approved Graph",
            style="Primary.TButton",
            command=self._start_codex_run,
        ).pack(side="right")

        notebook = ttk.Notebook(self.page)
        notebook.pack(fill="both", expand=True)

        graph_tab = ttk.Frame(
            notebook,
            style="Content.TFrame",
            padding=12,
        )
        notebook.add(graph_tab, text="Execution order")
        graph_view = tk.Text(
            graph_tab,
            wrap="word",
            borderwidth=1,
            relief="solid",
            font=("Menlo", 11),
        )
        graph_view.pack(fill="both", expand=True)
        node_by_id = {node.node_id: node for node in graph.nodes}
        for wave_number, wave in enumerate(graph.waves, start=1):
            graph_view.insert("end", f"WAVE {wave_number}\n")
            for node_id in wave:
                node = node_by_id[node_id]
                dependencies = ", ".join(node.depends_on) or "none"
                graph_view.insert(
                    "end",
                    (
                        f"  {node.node_id} · {node.agent_id} "
                        f"({node.agent_role})\n"
                        f"    Step: {node.title}\n"
                        f"    Depends on: {dependencies}\n"
                        f"    Token limit: {node.token_limit:,}\n"
                        f"    Owns: {len(node.owned_files)} file(s) · "
                        f"Reads: {len(node.read_only_files)} file(s)\n\n"
                    ),
                )
        graph_view.configure(state="disabled")

        ownership_tab = ttk.Frame(
            notebook,
            style="Content.TFrame",
            padding=12,
        )
        notebook.add(ownership_tab, text="File ownership")
        ownership_view = tk.Text(
            ownership_tab,
            wrap="word",
            borderwidth=1,
            relief="solid",
            font=("Menlo", 11),
        )
        ownership_view.pack(fill="both", expand=True)
        for item in graph.ownership:
            owner = item.owner_agent_id or "READ ONLY"
            readers = ", ".join(item.reader_agent_ids) or "none"
            ownership_view.insert(
                "end",
                (
                    f"{item.relative_path}\n"
                    f"  Owner: {owner}\n"
                    f"  Readers: {readers}\n"
                    f"  Reason: {item.reason}\n\n"
                ),
            )
        ownership_view.configure(state="disabled")

        ttk.Label(
            self.page,
            text=(
                f"{len(graph.protected_exclusions)} protected path(s) remain "
                "outside every agent node. The selected driver runs only after "
                "explicit user confirmation and stores progress, logs, session IDs, "
                "and mapped errors when supported."
            ),
            style="Body.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(12, 0))

    def _start_codex_run(self) -> None:
        if (
            self.current_project is None
            or self.current_context is None
            or self.current_budget is None
            or self.current_run_graph is None
        ):
            messagebox.showerror(
                "Run is not ready",
                "Open an approved Agent Run Graph before starting a driver.",
            )
            return

        inspection = self._selected_driver_inspection(refresh=True)
        controller = self.execution_controller
        if controller is None or not inspection.ready:
            message = inspection.message
            if inspection.remediation:
                message = f"{message}\n\n{inspection.remediation}"
            messagebox.showerror(
                f"{inspection.display_name} is unavailable",
                message,
            )
            return
        if controller.running:
            messagebox.showinfo(
                f"{inspection.display_name} is already running",
                "Wait for the active run to finish or cancel it from Runs.",
            )
            return

        confirmed = messagebox.askyesno(
            f"Run approved graph with {inspection.display_name}",
            (
                f"{inspection.display_name} will execute "
                f"{len(self.current_run_graph.nodes)} approved node(s) in "
                "dependency order. It will not commit, push, merge, tag, "
                "or publish. Continue?"
            ),
        )
        if not confirmed:
            return

        self.current_codex_run = None
        try:
            controller.start(
                graph=self.current_run_graph,
                selection=self.current_context,
                budget=self.current_budget,
                project=self.current_project.descriptor,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                f"Unable to start {inspection.display_name}",
                str(exc),
            )
            return
        self.show_page("codex-run")
        self.root.after(150, self._poll_codex_execution)

    def _render_codex_run(self) -> None:
        controller = self.execution_controller
        running = controller is not None and controller.running
        ttk.Button(
            self.page,
            text="← Agent Run Graph",
            style="Secondary.TButton",
            command=partial(self.show_page, "agent-run-graph"),
        ).pack(anchor="w", pady=(0, 18))
        ttk.Label(
            self.page,
            text="Codex Execution",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=(
                "Empy runs Codex outside the UI thread, streams structured progress, "
                "enforces timeout and cancellation, and preserves evidence per node."
            ),
            style="Body.TLabel",
            wraplength=840,
        ).pack(anchor="w", pady=(0, 14))

        controls = ttk.Frame(self.page, style="Content.TFrame")
        controls.pack(fill="x", pady=(0, 12))
        current_status = (
            self.current_codex_run.status
            if self.current_codex_run is not None
            else "running"
            if running
            else "not started"
        )
        self.codex_status_var = tk.StringVar(value=f"Status: {current_status}")
        ttk.Label(
            controls,
            textvariable=self.codex_status_var,
            style="CardTitle.TLabel",
        ).pack(side="left")
        self.codex_cancel_button = ttk.Button(
            controls,
            text="Cancel Run",
            style="Secondary.TButton",
            command=self._cancel_codex_run,
        )
        self.codex_cancel_button.pack(side="right")
        if not running:
            self.codex_cancel_button.state(["disabled"])

        log_frame = ttk.Frame(
            self.page,
            style="Content.TFrame",
            padding=2,
        )
        log_frame.pack(fill="both", expand=True)
        self.codex_log_view = tk.Text(
            log_frame,
            wrap="word",
            borderwidth=1,
            relief="solid",
            font=("Menlo", 11),
        )
        self.codex_log_view.pack(fill="both", expand=True)

        if self.current_codex_run is not None:
            for event in self.current_codex_run.events:
                self._append_codex_event(event)
            self.codex_log_view.insert("end", "\nNODE RESULTS\n")
            for node in self.current_codex_run.node_results:
                self.codex_log_view.insert(
                    "end",
                    (
                        f"{node.node_id}: {node.status}\n"
                        f"  Summary: {node.summary}\n"
                        f"  Session: {node.thread_id or 'not reported'}\n"
                        f"  Changed files: {', '.join(node.changed_files) or 'none reported'}\n"
                        f"  Events: {node.events_path}\n"
                        f"  Errors: {node.stderr_path}\n\n"
                    ),
                )
            if self.current_codex_run.error_message:
                self.codex_log_view.insert(
                    "end",
                    f"RUN ERROR: {self.current_codex_run.error_message}\n",
                )
        elif running:
            self.codex_log_view.insert(
                "end",
                "Codex preflight passed. Waiting for the first execution event...\n",
            )
        else:
            self.codex_log_view.insert("end", "No Codex run is selected.\n")
        self.codex_log_view.see("end")

    def _poll_codex_execution(self) -> None:
        controller = self.execution_controller
        if controller is None:
            return
        terminal_received = False
        for message in controller.drain():
            if isinstance(message, CodexProgressEvent):
                self._append_codex_event(message)
            elif isinstance(message, CodexGraphExecution):
                terminal_received = True
                self.current_codex_run = message
                if self.codex_status_var is not None:
                    self.codex_status_var.set(f"Status: {message.status}")
                if self.codex_cancel_button is not None:
                    self.codex_cancel_button.state(["disabled"])
                if self.codex_log_view is not None:
                    self.codex_log_view.insert(
                        "end",
                        (
                            f"\nRun finished: {message.status}\n"
                            f"Evidence saved under: {self.execution_store.run_root / message.run_id}\n"
                        ),
                    )
                    if message.error_message:
                        self.codex_log_view.insert(
                            "end",
                            f"Mapped error: {message.error_message}\n",
                        )
                    self.codex_log_view.see("end")
            elif isinstance(message, CodexControllerFailure):
                terminal_received = True
                if self.codex_status_var is not None:
                    self.codex_status_var.set("Status: failed")
                if self.codex_cancel_button is not None:
                    self.codex_cancel_button.state(["disabled"])
                messagebox.showerror("Codex execution failed", message.message)

        if controller.running or not terminal_received:
            self.root.after(150, self._poll_codex_execution)

    def _append_codex_event(self, event: CodexProgressEvent) -> None:
        if self.codex_log_view is None:
            return
        node = event.node_id or "runtime"
        self.codex_log_view.insert(
            "end",
            f"[{event.timestamp}] [{event.level.upper()}] [{node}] {event.message}\n",
        )
        self.codex_log_view.see("end")

    def _cancel_codex_run(self) -> None:
        controller = self.execution_controller
        if controller is None or not controller.running:
            return
        confirmed = messagebox.askyesno(
            "Cancel Codex run",
            "Stop the active Codex process and skip remaining nodes?",
        )
        if not confirmed:
            return
        controller.cancel()
        if self.codex_status_var is not None:
            self.codex_status_var.set("Status: cancelling")

    def _open_codex_run(self, run: CodexGraphExecution) -> None:
        self.current_codex_run = run
        self.show_page("codex-run")


    def _render_verification(self) -> None:
        ttk.Label(self.page, text="Verification", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text="Run the project-mapped tests, build, and lint commands. Stdout, stderr, and durable evidence stay visible inside Empy.",
            style="Body.TLabel",
            wraplength=840,
        ).pack(anchor="w", pady=(0, 16))

        controls = ttk.Frame(self.page, style="Content.TFrame")
        controls.pack(fill="x", pady=(0, 12))
        status = self.current_verification.status if self.current_verification is not None else "not run"
        self.verification_status_var = tk.StringVar(value=f"Status: {status}")
        ttk.Label(controls, textvariable=self.verification_status_var, style="CardTitle.TLabel").pack(side="left")
        ttk.Button(
            controls,
            text="Run Verification",
            style="Primary.TButton",
            command=self._start_verification,
        ).pack(side="right", padx=(8, 0))
        self.verification_finalize_button = ttk.Button(
            controls,
            text="Finalize",
            style="Secondary.TButton",
            command=self._finalize_verification,
        )
        self.verification_finalize_button.pack(side="right")

        notebook = ttk.Notebook(self.page)
        notebook.pack(fill="both", expand=True)
        for key, label in (("tests", "Tests"), ("build", "Build"), ("lint", "Lint"), ("evidence", "Evidence")):
            frame = ttk.Frame(notebook, style="Content.TFrame", padding=8)
            view = tk.Text(frame, wrap="word", borderwidth=1, relief="solid", font=("Menlo", 10))
            view.pack(fill="both", expand=True)
            notebook.add(frame, text=label)
            self.verification_views[key] = view

        report = self.current_verification
        if report is None and self.current_project is not None:
            reports = self.verification_store.list_reports(str(self.current_project.descriptor.root))
            report = reports[0] if reports else None
            self.current_verification = report
        if report is not None:
            self._display_verification_report(report)
        else:
            self.verification_views["evidence"].insert(
                "end",
                "No verification evidence is available for the selected project.\n",
            )
        self._update_finalize_state()

    def _start_verification(self) -> None:
        if self.current_project is None:
            messagebox.showerror("Project required", "Open a project before running verification.")
            return
        if self.verification_controller.running:
            return
        self.current_verification = None
        for view in self.verification_views.values():
            view.delete("1.0", "end")
        if self.verification_status_var is not None:
            self.verification_status_var.set("Status: running")
        self._update_finalize_state()
        try:
            self.verification_controller.start(self.current_project)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to run verification", str(exc))
            return
        self.root.after(100, self._poll_verification)

    def _poll_verification(self) -> None:
        terminal = False
        for message in self.verification_controller.drain():
            if isinstance(message, VerificationEvent):
                view = self.verification_views.get(message.category)
                if view is not None:
                    prefix = "STDERR" if message.stream == "stderr" else "STDOUT"
                    view.insert("end", f"[{prefix}] {message.text}")
                    view.see("end")
            elif isinstance(message, VerificationReport):
                terminal = True
                self.current_verification = message
                self._display_verification_report(message)
                if self.verification_status_var is not None:
                    self.verification_status_var.set(f"Status: {message.status}")
                self._update_finalize_state()
            elif isinstance(message, VerificationControllerFailure):
                terminal = True
                if self.verification_status_var is not None:
                    self.verification_status_var.set("Status: failed")
                self._update_finalize_state()
                messagebox.showerror("Verification failed", message.message)
        if self.verification_controller.running or not terminal:
            self.root.after(100, self._poll_verification)

    def _display_verification_report(self, report: VerificationReport) -> None:
        for result in report.results:
            view = self.verification_views.get(result.check.category)
            if view is not None:
                view.insert(
                    "end",
                    f"\n{result.check.label}: {result.status.upper()} (exit {result.returncode})\n",
                )
                view.see("end")
        evidence = self.verification_views.get("evidence")
        if evidence is not None:
            evidence.delete("1.0", "end")
            evidence.insert(
                "end",
                f"Verification ID: {report.verification_id}\n"
                f"Project: {report.project_root}\n"
                f"Status: {report.status}\n"
                f"Finalize allowed: {report.finalize_allowed}\n"
                f"Evidence path: {report.evidence_path}\n"
                f"Finalized at: {report.finalized_at or 'not finalized'}\n",
            )

    def _update_finalize_state(self) -> None:
        if self.verification_finalize_button is None:
            return
        allowed = self.current_verification is not None and self.current_verification.finalize_allowed
        if allowed:
            self.verification_finalize_button.state(["!disabled"])
        else:
            self.verification_finalize_button.state(["disabled"])

    def _finalize_verification(self) -> None:
        report = self.current_verification
        if report is None:
            return
        try:
            self.current_verification = self.verification_store.finalize(report.verification_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Finalize blocked", str(exc))
            return
        self._display_verification_report(self.current_verification)
        self._update_finalize_state()
        messagebox.showinfo("Verification finalized", "All verification gates passed and evidence was finalized.")

    def _render_runs(self) -> None:
        ttk.Label(
            self.page,
            text="Runs",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text="Codex execution history, statuses, session evidence, and mapped errors.",
            style="Body.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 18))

        project_root = (
            str(self.current_project.descriptor.root)
            if self.current_project is not None
            else None
        )
        runs = self.execution_store.list_runs(project_root=project_root)
        if not runs:
            self._empty_card(
                "No Codex runs yet",
                "Build an Agent Run Graph, lock its budget, and start Codex from the graph page.",
            ).pack(fill="x")
            return

        for run in runs:
            row = ttk.Frame(
                self.page,
                style="Card.TFrame",
                padding=16,
            )
            row.pack(fill="x", pady=(0, 10))
            text = ttk.Frame(row, style="Card.TFrame")
            text.pack(side="left", fill="both", expand=True)
            ttk.Label(
                text,
                text=f"{run.status.upper()} · {run.run_id[:12]}",
                style="CardTitle.TLabel",
            ).pack(anchor="w")
            ttk.Label(
                text,
                text=(
                    f"Graph {run.graph_id} · {len(run.node_results)} node(s) · "
                    f"Started {run.started_at}"
                ),
                style="CardBody.TLabel",
                wraplength=700,
            ).pack(anchor="w", pady=(5, 0))
            ttk.Button(
                row,
                text="Open",
                style="Secondary.TButton",
                command=partial(self._open_codex_run, run),
            ).pack(side="right")


    def _open_sync_report(self, sync_id: str) -> None:
        self.current_sync_id = sync_id
        self.selected_conflict_id = None
        self.show_page("sync-detail")

    def _render_sync_reports(self) -> None:
        ttk.Label(self.page, text="Sync Reports", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text="Review ordered agent patches. Conflicts remain blocked until you choose an explicit resolution.",
            style="Body.TLabel",
            wraplength=840,
        ).pack(anchor="w", pady=(0, 18))
        reports = tuple(reversed(self.sync_store.list_reports()))
        if not reports:
            self._empty_card("No sync reports yet", "Agent patch synchronization reports will appear here.").pack(fill="x")
            return
        for report in reports:
            row = ttk.Frame(self.page, style="Card.TFrame", padding=16)
            row.pack(fill="x", pady=(0, 10))
            text = ttk.Frame(row, style="Card.TFrame")
            text.pack(side="left", fill="both", expand=True)
            ttk.Label(text, text=f"{report.status.upper()} · {report.sync_id}", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(
                text,
                text=(f"{len(report.queue)} patch(es) · {len(report.unresolved_conflicts)} unresolved conflict(s) · {report.project_root}"),
                style="CardBody.TLabel",
                wraplength=720,
            ).pack(anchor="w", pady=(5, 0))
            ttk.Button(row, text="Review", style="Secondary.TButton", command=partial(self._open_sync_report, report.sync_id)).pack(side="right")

    def _render_sync_detail(self) -> None:
        if self.current_sync_id is None:
            self.show_page("sync")
            return
        try:
            report = self.sync_store.load(self.current_sync_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to open sync report", str(exc))
            self.show_page("sync")
            return
        toolbar = ttk.Frame(self.page, style="Content.TFrame")
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Button(toolbar, text="← Sync Reports", style="Secondary.TButton", command=lambda: self.show_page("sync")).pack(side="left")
        apply_button = ttk.Button(toolbar, text="Apply ordered changes", style="Primary.TButton", command=self._apply_current_sync)
        apply_button.pack(side="right")
        if report.status != "ready":
            apply_button.state(["disabled"])
        ttk.Label(self.page, text=f"Sync {report.sync_id}", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.page,
            text=f"Status: {report.status} · Queue: {len(report.queue)} · Unresolved: {len(report.unresolved_conflicts)}",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(0, 16))

        pane = ttk.Panedwindow(self.page, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, style="Card.TFrame", padding=12)
        right = ttk.Frame(pane, style="Card.TFrame", padding=12)
        pane.add(left, weight=1)
        pane.add(right, weight=2)
        ttk.Label(left, text="Conflicts", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        conflicts = ttk.Treeview(left, columns=("kind", "state"), show="tree headings", height=18)
        conflicts.heading("#0", text="File")
        conflicts.heading("kind", text="Type")
        conflicts.heading("state", text="State")
        conflicts.column("#0", width=220)
        conflicts.column("kind", width=130)
        conflicts.column("state", width=90)
        conflicts.pack(fill="both", expand=True)
        for conflict in report.conflicts:
            conflicts.insert("", "end", iid=conflict.conflict_id, text=conflict.relative_path, values=(conflict.kind, conflict.resolution or "unresolved"))
        conflicts.bind("<<TreeviewSelect>>", lambda _event: self._select_sync_conflict(conflicts))

        ttk.Label(right, text="Conflict decision", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.sync_conflict_detail = tk.Text(right, height=10, wrap="word", state="disabled")
        self.sync_conflict_detail.pack(fill="x", pady=(0, 10))
        ttk.Label(right, text="Manual merged content", style="Field.TLabel").pack(anchor="w", pady=(0, 5))
        self.sync_manual_view = tk.Text(right, height=12, wrap="none")
        self.sync_manual_view.pack(fill="both", expand=True, pady=(0, 10))
        actions = ttk.Frame(right, style="Card.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Apply patch", style="Secondary.TButton", command=lambda: self._resolve_selected_conflict("apply-patch")).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Keep current", style="Secondary.TButton", command=lambda: self._resolve_selected_conflict("keep-current")).pack(side="left", padx=6)
        ttk.Button(actions, text="Use manual content", style="Primary.TButton", command=lambda: self._resolve_selected_conflict("manual-content")).pack(side="left", padx=6)
        if report.conflicts:
            first = report.conflicts[0].conflict_id
            conflicts.selection_set(first)
            conflicts.focus(first)
            self._show_sync_conflict(first)

    def _select_sync_conflict(self, tree: ttk.Treeview) -> None:
        selected = tree.selection()
        if selected:
            self._show_sync_conflict(selected[0])

    def _show_sync_conflict(self, conflict_id: str) -> None:
        if self.current_sync_id is None:
            return
        report = self.sync_store.load(self.current_sync_id)
        conflict = next(item for item in report.conflicts if item.conflict_id == conflict_id)
        queue_item = next(item for item in report.queue if item.patch.patch_id == conflict.patch_id)
        self.selected_conflict_id = conflict_id
        detail = (
            f"File: {conflict.relative_path}\nType: {conflict.kind}\nMessage: {conflict.message}\n"
            f"Patch: {conflict.patch_id} ({queue_item.patch.operation})\nExpected SHA: {conflict.expected_sha256 or '-'}\n"
            f"Current SHA: {conflict.current_sha256 or '-'}\nCompeting patches: {', '.join(conflict.competing_patch_ids) or '-'}\n"
            f"Decision: {conflict.resolution or 'required'}"
        )
        self.sync_conflict_detail.configure(state="normal")
        self.sync_conflict_detail.delete("1.0", "end")
        self.sync_conflict_detail.insert("1.0", detail)
        self.sync_conflict_detail.configure(state="disabled")
        if self.sync_manual_view is not None:
            self.sync_manual_view.delete("1.0", "end")
            self.sync_manual_view.insert("1.0", conflict.manual_content if conflict.manual_content is not None else (queue_item.patch.content or ""))

    def _resolve_selected_conflict(self, choice: str) -> None:
        if self.current_sync_id is None or self.selected_conflict_id is None:
            messagebox.showerror("No conflict selected", "Select a conflict before recording a decision.")
            return
        manual = None
        if choice == "manual-content":
            manual = self.sync_manual_view.get("1.0", "end-1c") if self.sync_manual_view is not None else ""
        try:
            self.sync_store.resolve(self.current_sync_id, conflict_id=self.selected_conflict_id, choice=choice, manual_content=manual)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to resolve conflict", str(exc))
            return
        self.show_page("sync-detail")

    def _apply_current_sync(self) -> None:
        if self.current_sync_id is None:
            return
        if not messagebox.askyesno("Apply sync", "Apply the ordered patch queue to the project now?"):
            return
        try:
            self.sync_store.apply(self.current_sync_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to apply sync", str(exc))
            return
        messagebox.showinfo("Sync applied", "All approved changes were applied in queue order.")
        self.show_page("sync-detail")

    def _edit_task_from_plan(self) -> None:
        if (
            self.current_plan is not None
            and self.current_plan.status
            == "approved"
        ):
            messagebox.showerror(
                "Plan is locked",
                "Approved plans are immutable.",
            )
            return

        messagebox.showinfo(
            "Edit task",
            (
                "Return to Project Home and create "
                "a revised task. The approved plan "
                "will never be changed silently."
            ),
        )
        self.show_page("project-home")

    def _approve_plan(self) -> None:
        if (
            self.current_plan is None
            or self.current_task is None
        ):
            return

        confirmed = messagebox.askyesno(
            "Approve execution plan",
            (
                "Approval freezes this plan. "
                "Continue?"
            ),
        )
        if not confirmed:
            return

        try:
            approved = approve_execution_plan(
                self.current_plan,
                current_task=self.current_task,
            )
            self.plan_store.save_plan(approved)
            self.current_plan = approved
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Unable to approve plan",
                str(exc),
            )
            return

        messagebox.showinfo(
            "Plan approved",
            (
                "The plan is frozen and ready for "
                "bounded context and execution setup."
            ),
        )
        self.show_page("plan-preview")

    def _project_row(
        self,
        project: ProjectDescriptor,
    ) -> ttk.Frame:
        row = ttk.Frame(
            self.page,
            style="Card.TFrame",
            padding=16,
        )
        text = ttk.Frame(
            row,
            style="Card.TFrame",
        )
        text.pack(side="left", fill="both", expand=True)
        ttk.Label(
            text,
            text=project.display_name,
            style="CardTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            text,
            text=(
                f"{project.project_type} · {project.root}"
            ),
            style="CardBody.TLabel",
            wraplength=650,
        ).pack(anchor="w", pady=(5, 0))
        ttk.Button(
            row,
            text="Open",
            style="Secondary.TButton",
            command=partial(
                self.open_registered_project,
                project,
            ),
        ).pack(side="right")
        return row

    def _empty_card(
        self,
        title: str,
        body: str,
    ) -> ttk.Frame:
        card = ttk.Frame(
            self.page,
            style="Card.TFrame",
            padding=20,
        )
        ttk.Label(
            card,
            text=title,
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            card,
            text=body,
            style="CardBody.TLabel",
            wraplength=700,
        ).pack(anchor="w")
        return card

    def _metadata_card(
        self,
        parent: tk.Misc,
        title: str,
        value: str,
    ) -> ttk.Frame:
        card = ttk.Frame(
            parent,
            style="Card.TFrame",
            padding=18,
        )
        ttk.Label(
            card,
            text=title,
            style="CardBody.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            card,
            text=value,
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(8, 0))
        return card

    def _render_driver_settings(self) -> None:
        settings = self.driver_manager.settings
        inspections = {
            item.provider_id: item
            for item in self.driver_manager.inspections()
        }
        self.driver_enabled_vars = {}
        self.driver_executable_vars = {}
        self.driver_status_labels = {}

        ttk.Label(
            self.page,
            text="Driver Settings",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.page,
            text=(
                "AI providers are replaceable drivers. Empy stores provider "
                "configuration, executable paths, capability profiles, and "
                "availability without storing credential secrets."
            ),
            style="Body.TLabel",
            wraplength=850,
        ).pack(anchor="w", pady=(0, 18))

        top = ttk.Frame(self.page, style="Card.TFrame", padding=16)
        top.pack(fill="x", pady=(0, 14))
        ttk.Label(
            top,
            text="Default driver",
            style="CardTitle.TLabel",
        ).pack(side="left")
        self.driver_default_var = tk.StringVar(
            value=settings.default_provider
        )
        ttk.Combobox(
            top,
            textvariable=self.driver_default_var,
            values=tuple(
                item.provider_id
                for item in self.driver_registry.definitions()
            ),
            state="readonly",
            width=18,
        ).pack(side="left", padx=14)
        ttk.Button(
            top,
            text="Refresh Status",
            style="Secondary.TButton",
            command=self._refresh_driver_settings,
        ).pack(side="right")

        matrix = ttk.Frame(self.page, style="Content.TFrame")
        matrix.pack(fill="both", expand=True)
        for definition in self.driver_registry.definitions():
            configuration = settings.configuration_for(
                definition.provider_id
            )
            inspection = inspections[definition.provider_id]
            card = ttk.Frame(
                matrix,
                style="Card.TFrame",
                padding=16,
            )
            card.pack(fill="x", pady=6)

            heading = ttk.Frame(card, style="Card.TFrame")
            heading.pack(fill="x")
            ttk.Label(
                heading,
                text=definition.display_name,
                style="CardTitle.TLabel",
            ).pack(side="left")
            status_label = ttk.Label(
                heading,
                text=self._driver_status_text(inspection),
                style="CardBody.TLabel",
            )
            status_label.pack(side="right")
            self.driver_status_labels[definition.provider_id] = status_label

            ttk.Label(
                card,
                text=definition.description,
                style="CardBody.TLabel",
                wraplength=790,
            ).pack(anchor="w", pady=(6, 10))

            options = ttk.Frame(card, style="Card.TFrame")
            options.pack(fill="x")
            enabled_var = tk.BooleanVar(value=configuration.enabled)
            executable_var = tk.StringVar(
                value=configuration.executable or ""
            )
            self.driver_enabled_vars[definition.provider_id] = enabled_var
            self.driver_executable_vars[definition.provider_id] = executable_var
            ttk.Checkbutton(
                options,
                text="Enabled",
                variable=enabled_var,
            ).pack(side="left")
            ttk.Label(
                options,
                text="Executable",
                style="CardBody.TLabel",
            ).pack(side="left", padx=(20, 6))
            ttk.Entry(
                options,
                textvariable=executable_var,
                width=28,
            ).pack(side="left")
            ttk.Label(
                options,
                text=f"Credential: {configuration.credential_mode}",
                style="CardBody.TLabel",
            ).pack(side="right")

            capability_names = definition.capabilities.enabled_names()
            capability_text = (
                ", ".join(capability_names)
                if capability_names
                else "No executable capabilities in this build"
            )
            ttk.Label(
                card,
                text=f"Capabilities: {capability_text}",
                style="CardBody.TLabel",
                wraplength=790,
            ).pack(anchor="w", pady=(10, 0))

        actions = ttk.Frame(self.page, style="Content.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        ttk.Label(
            actions,
            text=(
                "Credential secrets are never written to driver-settings.json. "
                "CLI login or environment credentials remain provider-managed."
            ),
            style="Body.TLabel",
            wraplength=650,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Save Driver Settings",
            style="Primary.TButton",
            command=self._save_driver_settings,
        ).pack(side="right")

    @staticmethod
    def _driver_status_text(inspection: DriverInspection) -> str:
        implementation = (
            "implemented" if inspection.implemented else "not implemented"
        )
        return f"{inspection.availability} · {implementation}"

    def _refresh_driver_settings(self) -> None:
        try:
            self.driver_manager.inspections(refresh=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to inspect drivers", str(exc))
            return
        self.show_page("settings")

    def _save_driver_settings(self) -> None:
        if self.driver_default_var is None:
            return
        providers: list[DriverConfiguration] = []
        current = self.driver_manager.settings
        for definition in self.driver_registry.definitions():
            previous = current.configuration_for(definition.provider_id)
            executable = self.driver_executable_vars[
                definition.provider_id
            ].get().strip()
            providers.append(
                DriverConfiguration(
                    provider_id=definition.provider_id,
                    enabled=self.driver_enabled_vars[
                        definition.provider_id
                    ].get(),
                    executable=executable or None,
                    credential_mode=previous.credential_mode,
                    credential_environment_variable=(
                        previous.credential_environment_variable
                    ),
                )
            )
        settings = DriverSettings(
            schema_version=1,
            default_provider=self.driver_default_var.get(),
            providers=tuple(providers),
        )
        try:
            settings.validate()
            self.driver_settings_store.save(settings)
            self.driver_manager.replace_settings(settings)
            self._injected_codex_driver = None
            self._injected_execution_controller = None
            self._configure_selected_execution_controller()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Unable to save driver settings", str(exc))
            return
        messagebox.showinfo(
            "Driver settings saved",
            f"Default driver: {settings.default_provider}",
        )
        self.show_page("settings")

    def _render_placeholder(
        self,
        *,
        title: str,
        text: str,
    ) -> None:
        ttk.Label(
            self.page,
            text=title,
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            self.page,
            text=text,
            style="Body.TLabel",
            wraplength=720,
        ).pack(anchor="w")

    def _field_label(
        self,
        parent: tk.Misc,
        text: str,
    ) -> None:
        ttk.Label(
            parent,
            text=text,
            style="Field.TLabel",
        ).pack(anchor="w", pady=(0, 6))

    def _text_column(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str,
    ) -> tk.Text:
        frame = ttk.Frame(
            parent,
            style="Content.TFrame",
        )
        frame.pack(
            side="left",
            fill="both",
            expand=True,
            padx=6,
        )
        ttk.Label(
            frame,
            text=title,
            style="Field.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=subtitle,
            style="Body.TLabel",
        ).pack(anchor="w", pady=(2, 6))
        widget = tk.Text(
            frame,
            height=10,
            wrap="word",
        )
        widget.pack(fill="both", expand=True)
        return widget

    def _replace_text(
        self,
        widget: tk.Text,
        value: str,
    ) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)


def launch_desktop() -> None:
    root = tk.Tk()
    EmpyDesktopShell(root)
    root.mainloop()
