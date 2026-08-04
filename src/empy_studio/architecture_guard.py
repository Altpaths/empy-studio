from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BoundaryViolation:
    file: str
    imported_module: str
    rule: str


def inspect_architecture_boundaries(
    source_root: str | Path,
) -> tuple[BoundaryViolation, ...]:
    root = Path(source_root).expanduser().resolve()
    violations: list[BoundaryViolation] = []

    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts:
            continue

        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )

        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        if relative.startswith("core/"):
            for module in imports:
                if module.startswith("empy_studio.desktop"):
                    violations.append(
                        BoundaryViolation(
                            file=relative,
                            imported_module=module,
                            rule="core-must-not-import-desktop",
                        )
                    )
                if module.startswith("empy_studio.drivers"):
                    violations.append(
                        BoundaryViolation(
                            file=relative,
                            imported_module=module,
                            rule="core-must-not-import-drivers",
                        )
                    )

        if relative.startswith("desktop/"):
            for module in imports:
                if module.startswith("empy_studio.drivers."):
                    violations.append(
                        BoundaryViolation(
                            file=relative,
                            imported_module=module,
                            rule="desktop-must-use-driver-contracts",
                        )
                    )

    return tuple(violations)


def require_clean_architecture_boundaries(
    source_root: str | Path,
) -> None:
    violations = inspect_architecture_boundaries(source_root)
    if not violations:
        return

    detail = "\n".join(
        f"- {item.file}: {item.imported_module} ({item.rule})"
        for item in violations
    )
    raise RuntimeError(
        "Architecture boundary violations detected:\n" + detail
    )
