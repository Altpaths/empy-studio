from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.documentation_evidence import (
    DocumentationConfig,
    DocumentationRequirement,
    default_documentation_config,
    require_documentation_ready,
    run_documentation_validation,
)


def project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "project"
    root.mkdir()

    (root / "pyproject.toml").write_text(
        "[project]\nname='example'\n",
        encoding="utf-8",
    )

    docs = root / "docs"
    docs.mkdir()

    (docs / "getting-started.en.md").write_text(
        "# Empy Studio\n"
        "## Installation\n"
        "## First workflow\n"
        "## Release safety\n",
        encoding="utf-8",
    )
    (docs / "getting-started.fa.md").write_text(
        "# راهنمای Empy Studio\n"
        "## نصب\n"
        "## نخستین گردش کار\n"
        "## ایمنی انتشار\n",
        encoding="utf-8",
    )
    (docs / "example-project.en.md").write_text(
        "# Example project\n"
        "## Structure\n"
        "## Run\n"
        "## Expected evidence\n",
        encoding="utf-8",
    )
    (docs / "example-project.fa.md").write_text(
        "# پروژه نمونه\n"
        "## ساختار\n"
        "## اجرا\n"
        "## شواهد مورد انتظار\n",
        encoding="utf-8",
    )

    example = (
        root / "examples" / "v1-sample-project"
    )
    (example / "input").mkdir(
        parents=True
    )

    for relative in (
        "AGENTS.md",
        "README.md",
        "task-contract.json",
        "runtime-manifest.json",
        "input/customer-request.md",
    ):
        path = example / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            f"content for {relative}\n",
            encoding="utf-8",
        )

    return root


def test_default_documentation_passes(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    evidence = (
        run_documentation_validation(
            default_documentation_config(
                root,
                tmp_path / "documentation.json",
            )
        )
    )

    assert evidence.status == "passed"
    assert len(evidence.documentation) == 4
    assert evidence.example_project.passed
    assert (
        evidence.example_project.sha256
        is not None
    )


def test_missing_section_fails(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "docs"
        / "getting-started.en.md"
    ).write_text(
        "# Empy Studio\n"
        "## Installation\n",
        encoding="utf-8",
    )

    evidence = (
        run_documentation_validation(
            default_documentation_config(
                root,
                tmp_path / "documentation.json",
            )
        )
    )

    assert evidence.status == "failed"
    english = next(
        item
        for item in evidence.documentation
        if item.path
        == "docs/getting-started.en.md"
    )
    assert "## First workflow" in (
        english.missing_sections
    )


def test_missing_example_file_fails(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "examples"
        / "v1-sample-project"
        / "task-contract.json"
    ).unlink()

    evidence = (
        run_documentation_validation(
            default_documentation_config(
                root,
                tmp_path / "documentation.json",
            )
        )
    )

    assert evidence.status == "failed"
    assert (
        "task-contract.json"
        in evidence.example_project.missing_files
    )


def test_evidence_is_deterministic(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    first = run_documentation_validation(
        default_documentation_config(
            root,
            tmp_path / "first.json",
        )
    )
    second = run_documentation_validation(
        default_documentation_config(
            root,
            tmp_path / "second.json",
        )
    )

    assert (
        first.example_project.sha256
        == second.example_project.sha256
    )


def test_require_documentation_ready_raises(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "docs"
        / "getting-started.fa.md"
    ).unlink()

    evidence = (
        run_documentation_validation(
            default_documentation_config(
                root,
                tmp_path / "documentation.json",
            )
        )
    )

    with pytest.raises(
        RuntimeError,
        match="getting-started.fa.md",
    ):
        require_documentation_ready(
            evidence
        )


def test_rejects_unsafe_path(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    with pytest.raises(
        ValueError,
        match="safe relative paths",
    ):
        DocumentationConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "documentation.json"
            ),
            requirements=(
                DocumentationRequirement(
                    language="en",
                    path="../outside.md",
                    required_sections=(
                        "# Outside",
                    ),
                ),
            ),
            example_root=(
                "examples/v1-sample-project"
            ),
            example_required_files=(
                "README.md",
            ),
        ).validate()


def test_rejects_empty_sections() -> None:
    with pytest.raises(
        ValueError,
        match="sections cannot be empty",
    ):
        DocumentationRequirement(
            language="en",
            path="docs/test.md",
            required_sections=(),
        ).validate()
