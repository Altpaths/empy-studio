from __future__ import annotations

import tkinter as tk
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from empy_studio.core import (
    TASK_TEMPLATES,
    ContextSelection,
    DefaultProjectService,
    ExecutionPlan,
    ProductTask,
    ProjectDescriptor,
    ProjectDetection,
    TaskKind,
    approve_execution_plan,
    build_context_selection,
    build_product_task,
    generate_execution_plan,
    mark_ready_for_planning,
    template_by_key,
)

from .context_workspace_adapter import (
    ContextWorkspaceAdapter,
)
from .plan_workspace_adapter import (
    PlanWorkspaceAdapter,
)
from .task_workspace_adapter import (
    TaskWorkspaceAdapter,
)
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
        key="settings",
        label="Settings",
        description="Workspace and driver settings.",
    ),
)


class EmpyDesktopShell:
    """Desktop product shell through Ticket 8."""

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
        self.current_project: (
            ProjectDetection | None
        ) = None
        self.current_task: (
            ProductTask | None
        ) = None
        self.current_plan: ExecutionPlan | None = None
        self.current_context: ContextSelection | None = None
        self.selected_template: TaskKind = "custom"

        self._configure_window()
        self._configure_styles()
        self._build_layout()
        self.show_page("home")

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
            text="Ticket 8 · Context Selector",
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
            self._render_placeholder(
                title="Runs",
                text=(
                    "Execution history enters "
                    "the product in later roadmap tickets."
                ),
            )
        elif key == "settings":
            self._render_placeholder(
                title="Settings",
                text=(
                    "Driver settings are outside Ticket 6."
                ),
            )
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
            command=lambda: self.show_page("plan-preview"),
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

        ttk.Label(
            self.page,
            text=(
                "Context is visible and bounded. No agent has been dispatched; "
                "Token Budget Controller remains Ticket 9."
            ),
            style="Body.TLabel",
            wraplength=800,
        ).pack(anchor="w", pady=(12, 0))

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
                "Ticket 8: Context Selector."
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
