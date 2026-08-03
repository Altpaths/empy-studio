from __future__ import annotations

import json
from pathlib import Path

import pytest

from empy_studio.codex_materializer import (
    load_materialized_manifest,
    materialize_codex_run,
)
from empy_studio.codex_workflow import (
    CodexExecutionPolicy,
    CodexRunManifest,
    CodexTaskContract,
)


def planned_manifest(
    tmp_path: Path,
    *,
    context_package: str | None = None,
    run_id: str = "run-001",
) -> CodexRunManifest:
    return CodexRunManifest(
        run_id=run_id,
        project_root=str(tmp_path.resolve()),
        task=CodexTaskContract(
            task_id="ticket-5.2",
            title="Materialize Codex context",
            objective="Prepare bounded Codex input files.",
            acceptance_criteria=(
                "AGENTS.md is created",
                "Prompt is created",
                "Manifest is persisted",
            ),
            allowed_paths=("src/", "tests/"),
            forbidden_paths=(".env",),
            verification_commands=(
                "python -m pytest -q",
            ),
            constraints=(
                "Do not change public APIs unnecessarily",
            ),
        ),
        policy=CodexExecutionPolicy(),
        context_package=context_package,
    )


def test_materializes_agents_prompt_and_manifest(
    tmp_path: Path,
) -> None:
    prepared = materialize_codex_run(
        planned_manifest(tmp_path),
        tmp_path / "runs",
    )

    assert prepared.status == "prepared"
    assert prepared.agents_file is not None
    assert prepared.prompt_file is not None
    assert prepared.evidence_dir is not None

    agents = Path(prepared.agents_file).read_text(
        encoding="utf-8"
    )
    prompt = Path(prepared.prompt_file).read_text(
        encoding="utf-8"
    )

    assert "## Acceptance criteria" in agents
    assert "`src/`" in agents
    assert "`.env`" in agents
    assert "Task ID: `ticket-5.2`" in prompt

    persisted = load_materialized_manifest(
        Path(prepared.agents_file).parent
        / "manifest.json"
    )
    assert persisted.to_dict() == prepared.to_dict()


def test_copies_directory_context_package(
    tmp_path: Path,
) -> None:
    context = tmp_path / "context-source"
    context.mkdir()
    (context / "summary.md").write_text(
        "bounded context",
        encoding="utf-8",
    )

    prepared = materialize_codex_run(
        planned_manifest(
            tmp_path,
            context_package=str(context),
        ),
        tmp_path / "runs",
    )

    assert prepared.context_package is not None
    copied = Path(prepared.context_package)
    assert (copied / "summary.md").read_text(
        encoding="utf-8"
    ) == "bounded context"


def test_copies_file_context_package(
    tmp_path: Path,
) -> None:
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps({"files": ["src/example.py"]}),
        encoding="utf-8",
    )

    prepared = materialize_codex_run(
        planned_manifest(
            tmp_path,
            context_package=str(context),
        ),
        tmp_path / "runs",
    )

    assert prepared.context_package is not None
    copied = Path(prepared.context_package)
    assert copied.name == "context.json"
    assert copied.is_file()


def test_rejects_materializing_non_planned_run(
    tmp_path: Path,
) -> None:
    manifest = planned_manifest(tmp_path)
    manifest.status = "manual_required"

    with pytest.raises(
        ValueError,
        match="Only planned",
    ):
        materialize_codex_run(
            manifest,
            tmp_path / "runs",
        )


def test_rejects_existing_run_directory(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    (runs_root / "run-001").mkdir(
        parents=True,
    )

    with pytest.raises(FileExistsError):
        materialize_codex_run(
            planned_manifest(tmp_path),
            runs_root,
        )


def test_missing_context_removes_partial_run(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"

    with pytest.raises(FileNotFoundError):
        materialize_codex_run(
            planned_manifest(
                tmp_path,
                context_package=str(
                    tmp_path / "missing-context"
                ),
            ),
            runs_root,
        )

    assert not (runs_root / "run-001").exists()


def test_sanitizes_run_directory_name(
    tmp_path: Path,
) -> None:
    prepared = materialize_codex_run(
        planned_manifest(
            tmp_path,
            run_id="../unsafe run",
        ),
        tmp_path / "runs",
    )

    run_dir = Path(prepared.agents_file).parent
    assert run_dir.parent == (tmp_path / "runs").resolve()
    assert run_dir.name == "___unsafe_run"
