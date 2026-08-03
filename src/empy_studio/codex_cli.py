from __future__ import annotations

from typing import Any

from .codex_doctor import diagnose_codex_environment
from .codex_runtime import (
    codex_run_status,
    create_manual_handoff,
    run_codex_workflow,
)


def codex_doctor_command(
    manifest: str,
    codex_executable: str,
) -> dict[str, Any]:
    return diagnose_codex_environment(
        manifest,
        codex_executable=codex_executable,
    )


def codex_run_command(
    manifest: str,
    codex_executable: str,
    no_manual_fallback: bool,
) -> dict[str, Any]:
    return run_codex_workflow(
        manifest,
        codex_executable=codex_executable,
        allow_manual_fallback=not no_manual_fallback,
    ).to_dict()


def codex_resume_command(
    manifest: str,
    prompt: str,
    codex_executable: str,
) -> dict[str, Any]:
    return run_codex_workflow(
        manifest,
        follow_up_prompt=prompt,
        codex_executable=codex_executable,
    ).to_dict()


def codex_manual_command(
    manifest: str,
    reason: str,
) -> dict[str, Any]:
    return create_manual_handoff(manifest, reason=reason)


def codex_status_command(manifest: str) -> dict[str, Any]:
    return codex_run_status(manifest)
