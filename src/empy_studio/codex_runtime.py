from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .codex_doctor import diagnose_codex_environment
from .codex_exec_adapter import execute_codex_run
from .codex_materializer import load_materialized_manifest
from .codex_session import resume_codex_run
from .codex_workflow import CodexRunManifest

MANUAL_HANDOFF_NAME = "manual-handoff.json"


@dataclass(frozen=True)
class CodexWorkflowResult:
    status: str
    run_id: str
    mode: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _save_manifest(path: Path, manifest: CodexRunManifest) -> None:
    _write_json_atomic(path, manifest.to_dict())


def create_manual_handoff(
    manifest_path: str | Path,
    *,
    reason: str,
) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    manifest = load_materialized_manifest(path)

    if manifest.agents_file is None:
        raise ValueError("Run Manifest is missing agents_file")
    if manifest.prompt_file is None:
        raise ValueError("Run Manifest is missing prompt_file")
    if manifest.evidence_dir is None:
        raise ValueError("Run Manifest is missing evidence_dir")

    evidence_dir = Path(manifest.evidence_dir)
    handoff_path = evidence_dir / MANUAL_HANDOFF_NAME
    handoff = {
        "status": "manual_required",
        "run_id": manifest.run_id,
        "reason": reason,
        "project_root": manifest.project_root,
        "agents_file": manifest.agents_file,
        "prompt_file": manifest.prompt_file,
        "evidence_dir": manifest.evidence_dir,
        "thread_id": manifest.thread_id,
    }
    _write_json_atomic(handoff_path, handoff)

    updated = replace(
        manifest,
        status="manual_required",
        metadata={
            **manifest.metadata,
            "manual_reason": reason,
            "manual_handoff": str(handoff_path),
        },
    )
    _save_manifest(path, updated)
    return handoff


def run_codex_workflow(
    manifest_path: str | Path,
    *,
    follow_up_prompt: str | None = None,
    codex_executable: str = "codex",
    allow_manual_fallback: bool = True,
) -> CodexWorkflowResult:
    path = Path(manifest_path).expanduser().resolve()
    manifest = load_materialized_manifest(path)

    if manifest.status == "prepared":
        diagnosis = diagnose_codex_environment(
            path,
            codex_executable=codex_executable,
        )
        if diagnosis["status"] != "ready":
            if not allow_manual_fallback:
                raise RuntimeError("Codex environment is not ready")
            handoff = create_manual_handoff(
                path,
                reason="Codex environment is not ready",
            )
            return CodexWorkflowResult(
                status="manual_required",
                run_id=manifest.run_id,
                mode="manual",
                details={"doctor": diagnosis, "handoff": handoff},
            )

        execute_result = execute_codex_run(
            path,
            codex_executable=codex_executable,
        )
        return CodexWorkflowResult(
            status=execute_result.status,
            run_id=execute_result.run_id,
            mode="execute",
            details=execute_result.to_dict(),
        )

    if manifest.status in {"completed", "failed"}:
        if follow_up_prompt is None:
            raise ValueError(
                "follow_up_prompt is required to resume a run"
            )
        resume_result = resume_codex_run(
            path,
            follow_up_prompt,
            codex_executable=codex_executable,
        )
        return CodexWorkflowResult(
            status=resume_result.status,
            run_id=resume_result.run_id,
            mode="resume",
            details=resume_result.to_dict(),
        )

    if manifest.status == "manual_required":
        return CodexWorkflowResult(
            status="manual_required",
            run_id=manifest.run_id,
            mode="manual",
            details={
                "handoff_path": manifest.metadata.get("manual_handoff")
            },
        )

    raise ValueError(
        f"Run status cannot be dispatched: {manifest.status}"
    )


def codex_run_status(manifest_path: str | Path) -> dict[str, Any]:
    manifest = load_materialized_manifest(manifest_path)
    return {
        "run_id": manifest.run_id,
        "status": manifest.status,
        "thread_id": manifest.thread_id,
        "project_root": manifest.project_root,
        "evidence_dir": manifest.evidence_dir,
        "metadata": manifest.metadata,
    }
