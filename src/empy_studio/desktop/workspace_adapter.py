from __future__ import annotations

from pathlib import Path
from typing import Any

from empy_studio.core import ProjectDescriptor


class DesktopWorkspaceAdapter:
    """Thin adapter over the Ticket 3 workspace persistence layer."""

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
        self._store = self._create_store()

    def _create_store(self) -> Any:
        candidates = (
            (
                "empy_studio.workspace",
                "WorkspaceStore",
            ),
            (
                "empy_studio.workspace_store",
                "WorkspaceStore",
            ),
            (
                "empy_studio.workspace_persistence",
                "WorkspaceStore",
            ),
            (
                "empy_studio.core.workspace",
                "WorkspaceStore",
            ),
        )

        for module_name, class_name in candidates:
            try:
                module = __import__(
                    module_name,
                    fromlist=[class_name],
                )
                cls = getattr(module, class_name)
            except (
                ImportError,
                AttributeError,
            ):
                continue

            for value in (
                self.workspace_root / "workspace.db",
                self.workspace_root,
            ):
                try:
                    return cls(value)
                except TypeError:
                    continue

        return _FallbackWorkspaceStore(
            self.workspace_root
            / "projects.json"
        )

    def save_project(
        self,
        project: ProjectDescriptor,
    ) -> None:
        project.validate()

        methods = (
            "save_project",
            "upsert_project",
            "add_project",
            "register_project",
        )
        for name in methods:
            method = getattr(
                self._store,
                name,
                None,
            )
            if method is None:
                continue
            try:
                method(project)
                return
            except TypeError:
                try:
                    method(
                        root=str(project.root),
                        project_type=project.project_type,
                        display_name=project.display_name,
                    )
                    return
                except TypeError:
                    continue

        raise RuntimeError(
            "Workspace store does not expose "
            "a supported project-save method"
        )

    def list_projects(
        self,
    ) -> tuple[ProjectDescriptor, ...]:
        methods = (
            "list_projects",
            "recent_projects",
            "get_projects",
        )
        for name in methods:
            method = getattr(
                self._store,
                name,
                None,
            )
            if method is None:
                continue

            values = method()
            return tuple(
                self._to_descriptor(item)
                for item in values
            )

        return ()

    def _to_descriptor(
        self,
        value: Any,
    ) -> ProjectDescriptor:
        if isinstance(
            value,
            ProjectDescriptor,
        ):
            return value

        if isinstance(value, dict):
            raw_root = (
                value.get("root")
                or value.get("project_root")
                or value.get("path")
            )
            if not isinstance(raw_root, (str, Path)):
                raise TypeError(
                    "Stored project is missing a valid root path"
                )
            root = Path(raw_root)
            raw_display_name = (
                value.get("display_name")
                or value.get("name")
            )
            return ProjectDescriptor(
                root=root,
                project_type=str(
                    value.get("project_type")
                    or value.get("type")
                    or "generic"
                ),
                display_name=(
                    str(raw_display_name)
                    if raw_display_name is not None
                    else root.name
                ),
            )

        root = Path(
            getattr(
                value,
                "root",
                getattr(
                    value,
                    "project_root",
                    value.path,
                ),
            )
        )
        return ProjectDescriptor(
            root=root,
            project_type=str(
                getattr(
                    value,
                    "project_type",
                    getattr(
                        value,
                        "type",
                        "generic",
                    ),
                )
            ),
            display_name=str(
                getattr(
                    value,
                    "display_name",
                    getattr(
                        value,
                        "name",
                        root.name,
                    ),
                )
            ),
        )


class _FallbackWorkspaceStore:
    def __init__(
        self,
        path: Path,
    ) -> None:
        self.path = path

    def save_project(
        self,
        project: ProjectDescriptor,
    ) -> None:
        import json

        existing = {
            item["root"]: item
            for item in self._read()
        }
        existing[str(project.root)] = {
            "root": str(project.root),
            "project_type": (
                project.project_type
            ),
            "display_name": (
                project.display_name
            ),
        }
        self.path.write_text(
            json.dumps(
                list(existing.values()),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def list_projects(
        self,
    ) -> tuple[ProjectDescriptor, ...]:
        return tuple(
            ProjectDescriptor(
                root=Path(item["root"]),
                project_type=item[
                    "project_type"
                ],
                display_name=item[
                    "display_name"
                ],
            )
            for item in self._read()
        )

    def _read(self) -> list[dict[str, str]]:
        import json

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
