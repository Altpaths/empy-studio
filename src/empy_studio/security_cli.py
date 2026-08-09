from __future__ import annotations

import sys
from typing import Any

from .security_audit import (
    SecurityAuditConfig,
    run_security_audit,
)


def security_audit_command(
    project_root: str,
    evidence_path: str,
    *,
    python_executable: str | None = None,
    source_directory: str = "src",
) -> dict[str, Any]:
    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=project_root,
            evidence_path=evidence_path,
            python_executable=(
                python_executable or sys.executable
            ),
            source_directory=source_directory,
        )
    )
    return evidence.to_dict()
