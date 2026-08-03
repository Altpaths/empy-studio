from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from .codex_workflow import CodexRunManifest

MANIFEST_NAME = "manifest.json"
AGENTS_NAME = "AGENTS.md"
PROMPT_NAME = "prompt.md"
CONTEXT_DIR = "context"
EVIDENCE_DIR = "evidence"


def _write_text_atomic(
    path: Path,
    content: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        content.rstrip() + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_run_directory(
    runs_root: Path,
    run_id: str,
) -> Path:
    safe_run_id = "".join(
        char
        if char.isalnum() or char in "-_"
        else "_"
        for char in run_id
    )
    if not safe_run_id:
        raise ValueError("run_id cannot resolve to an empty directory name")

    run_dir = (runs_root / safe_run_id).resolve()
    resolved_root = runs_root.resolve()

    if run_dir.parent != resolved_root:
        raise ValueError("Run directory escapes runs_root")

    return run_dir


def _render_agents(manifest: CodexRunManifest) -> str:
    task = manifest.task

    lines = [
        "# Empy Studio Codex Run",
        "",
        "## Objective",
        "",
        task.objective,
        "",
        "## Acceptance criteria",
        "",
    ]

    lines.extend(
        f"- {item}"
        for item in task.acceptance_criteria
    )

    lines.extend(
        [
            "",
            "## Allowed paths",
            "",
        ]
    )
    if task.allowed_paths:
        lines.extend(
            f"- `{item}`"
            for item in task.allowed_paths
        )
    else:
        lines.append("- No explicit path allowlist was provided.")

    lines.extend(
        [
            "",
            "## Forbidden paths",
            "",
        ]
    )
    if task.forbidden_paths:
        lines.extend(
            f"- `{item}`"
            for item in task.forbidden_paths
        )
    else:
        lines.append("- No additional forbidden paths were provided.")

    lines.extend(
        [
            "",
            "## Constraints",
            "",
        ]
    )
    if task.constraints:
        lines.extend(
            f"- {item}"
            for item in task.constraints
        )
    else:
        lines.append("- Preserve existing project conventions.")

    lines.extend(
        [
            "",
            "## Verification",
            "",
        ]
    )
    if task.verification_commands:
        lines.extend(
            f"- `{item}`"
            for item in task.verification_commands
        )
    else:
        lines.append("- No verification command was declared.")

    lines.extend(
        [
            "",
            "## Operating rules",
            "",
            "- Work only on the declared task.",
            "- Do not broaden scope without explicit evidence.",
            "- Preserve existing architecture and public contracts.",
            "- Record meaningful failures and verification results.",
            "- Do not expose secrets or modify forbidden paths.",
        ]
    )

    return "\n".join(lines)


def _render_prompt(manifest: CodexRunManifest) -> str:
    task = manifest.task

    lines = [
        f"# Task: {task.title}",
        "",
        f"Task ID: `{task.task_id}`",
        "",
        "Complete the objective using the bounded project context.",
        "",
        "## Objective",
        "",
        task.objective,
        "",
        "## Required outcome",
        "",
    ]
    lines.extend(
        f"{index}. {criterion}"
        for index, criterion in enumerate(
            task.acceptance_criteria,
            start=1,
        )
    )

    lines.extend(
        [
            "",
            "Before finishing:",
            "",
            "1. Review the diff for scope drift.",
            "2. Run the declared verification commands.",
            "3. Report changed files, checks, and unresolved risks.",
        ]
    )

    return "\n".join(lines)


def _copy_context_package(
    source: Path,
    destination: Path,
) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)

    if destination.exists():
        raise FileExistsError(destination)

    if source.is_dir():
        shutil.copytree(source, destination)
        return destination

    destination.mkdir(parents=True)
    target = destination / source.name
    shutil.copy2(source, target)
    return target


def materialize_codex_run(
    manifest: CodexRunManifest,
    runs_root: str | Path,
) -> CodexRunManifest:
    if manifest.status != "planned":
        raise ValueError(
            "Only planned Codex runs can be materialized"
        )

    root = Path(runs_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    run_dir = _safe_run_directory(
        root,
        manifest.run_id,
    )
    if run_dir.exists():
        raise FileExistsError(run_dir)

    run_dir.mkdir(parents=False)

    agents_path = run_dir / AGENTS_NAME
    prompt_path = run_dir / PROMPT_NAME
    evidence_path = run_dir / EVIDENCE_DIR
    evidence_path.mkdir()

    context_result: Path | None = None

    try:
        _write_text_atomic(
            agents_path,
            _render_agents(manifest),
        )
        _write_text_atomic(
            prompt_path,
            _render_prompt(manifest),
        )

        if manifest.context_package is not None:
            context_result = _copy_context_package(
                Path(manifest.context_package).expanduser().resolve(),
                run_dir / CONTEXT_DIR,
            )

        prepared = replace(
            manifest,
            agents_file=str(agents_path),
            prompt_file=str(prompt_path),
            evidence_dir=str(evidence_path),
            context_package=(
                str(context_result)
                if context_result is not None
                else None
            ),
            status="prepared",
        )
        prepared.validate()

        _write_json_atomic(
            run_dir / MANIFEST_NAME,
            prepared.to_dict(),
        )

        return prepared

    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def load_materialized_manifest(
    manifest_path: str | Path,
) -> CodexRunManifest:
    path = Path(manifest_path).expanduser().resolve()
    value = json.loads(
        path.read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise TypeError(
            "Materialized manifest must contain a JSON object"
        )
    return CodexRunManifest.from_dict(value)
