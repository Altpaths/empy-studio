from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

DocumentationLanguage = Literal[
    "en",
    "fa",
]


@dataclass(frozen=True)
class DocumentationRequirement:
    language: DocumentationLanguage
    path: str
    required_sections: tuple[str, ...]

    def validate(self) -> None:
        if self.language not in {
            "en",
            "fa",
        }:
            raise ValueError(
                "Unsupported documentation language"
            )
        if not self.path.strip():
            raise ValueError(
                "Documentation path cannot be empty"
            )
        if not self.required_sections:
            raise ValueError(
                "Documentation sections cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentationCheck:
    language: DocumentationLanguage
    path: str
    exists: bool
    non_empty: bool
    missing_sections: tuple[str, ...]
    sha256: str | None

    @property
    def passed(self) -> bool:
        return (
            self.exists
            and self.non_empty
            and not self.missing_sections
            and self.sha256 is not None
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["passed"] = self.passed
        return value


@dataclass(frozen=True)
class ExampleProjectCheck:
    root: str
    required_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    sha256: str | None

    @property
    def passed(self) -> bool:
        return (
            not self.missing_files
            and self.sha256 is not None
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["passed"] = self.passed
        return value


@dataclass(frozen=True)
class DocumentationEvidence:
    schema_version: int
    status: str
    project_root: str
    documentation: tuple[DocumentationCheck, ...]
    example_project: ExampleProjectCheck

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported documentation evidence schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported documentation evidence status"
            )
        if not self.documentation:
            raise ValueError(
                "Documentation evidence must contain checks"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_root": self.project_root,
            "documentation": [
                item.to_dict()
                for item in self.documentation
            ],
            "example_project": (
                self.example_project.to_dict()
            ),
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path


@dataclass(frozen=True)
class DocumentationConfig:
    project_root: str
    evidence_path: str
    requirements: tuple[
        DocumentationRequirement,
        ...
    ]
    example_root: str
    example_required_files: tuple[str, ...]

    def validate(self) -> None:
        root = Path(
            self.project_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise NotADirectoryError(root)
        if not (
            root / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "project_root must contain pyproject.toml"
            )
        if not self.requirements:
            raise ValueError(
                "Documentation requirements cannot be empty"
            )
        if not self.example_required_files:
            raise ValueError(
                "Example required files cannot be empty"
            )

        for requirement in self.requirements:
            requirement.validate()

        for relative in (
            self.example_root,
            *(
                requirement.path
                for requirement in self.requirements
            ),
            *self.example_required_files,
        ):
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "Documentation paths must be safe relative paths"
                )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(
            root
        ).as_posix()
        digest.update(
            relative.encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(
            path.read_bytes()
        )

    return digest.hexdigest()


def _check_document(
    project_root: Path,
    requirement: DocumentationRequirement,
) -> DocumentationCheck:
    path = (
        project_root / requirement.path
    ).resolve()

    if (
        project_root not in path.parents
        and path != project_root
    ):
        raise ValueError(
            "Documentation path escapes project root"
        )

    if not path.is_file():
        return DocumentationCheck(
            language=requirement.language,
            path=requirement.path,
            exists=False,
            non_empty=False,
            missing_sections=(
                requirement.required_sections
            ),
            sha256=None,
        )

    text = path.read_text(
        encoding="utf-8"
    )
    non_empty = bool(text.strip())

    missing_sections = tuple(
        section
        for section in requirement.required_sections
        if section not in text
    )

    return DocumentationCheck(
        language=requirement.language,
        path=requirement.path,
        exists=True,
        non_empty=non_empty,
        missing_sections=missing_sections,
        sha256=_file_sha256(path),
    )


def _check_example_project(
    project_root: Path,
    example_root: str,
    required_files: tuple[str, ...],
) -> ExampleProjectCheck:
    root = (
        project_root / example_root
    ).resolve()

    if (
        project_root not in root.parents
        and root != project_root
    ):
        raise ValueError(
            "Example project path escapes project root"
        )

    missing: list[str] = []

    for relative in required_files:
        path = (
            root / relative
        ).resolve()

        if (
            root not in path.parents
            and path != root
        ):
            raise ValueError(
                "Example file path escapes example root"
            )

        if not path.is_file():
            missing.append(relative)

    digest = (
        _tree_sha256(root)
        if root.is_dir() and not missing
        else None
    )

    return ExampleProjectCheck(
        root=example_root,
        required_files=required_files,
        missing_files=tuple(
            sorted(missing)
        ),
        sha256=digest,
    )


def run_documentation_validation(
    config: DocumentationConfig,
) -> DocumentationEvidence:
    config.validate()

    root = Path(
        config.project_root
    ).expanduser().resolve()

    documentation = tuple(
        _check_document(
            root,
            requirement,
        )
        for requirement in config.requirements
    )

    example_project = (
        _check_example_project(
            root,
            config.example_root,
            config.example_required_files,
        )
    )

    evidence = DocumentationEvidence(
        schema_version=1,
        status=(
            "passed"
            if all(
                item.passed
                for item in documentation
            )
            and example_project.passed
            else "failed"
        ),
        project_root=str(root),
        documentation=documentation,
        example_project=example_project,
    )
    evidence.save(
        config.evidence_path
    )
    return evidence


def default_documentation_config(
    project_root: str | Path,
    evidence_path: str | Path,
) -> DocumentationConfig:
    return DocumentationConfig(
        project_root=str(project_root),
        evidence_path=str(evidence_path),
        requirements=(
            DocumentationRequirement(
                language="en",
                path=(
                    "docs/getting-started.en.md"
                ),
                required_sections=(
                    "# Empy Studio",
                    "## Installation",
                    "## First workflow",
                    "## Release safety",
                ),
            ),
            DocumentationRequirement(
                language="fa",
                path=(
                    "docs/getting-started.fa.md"
                ),
                required_sections=(
                    "# راهنمای Empy Studio",
                    "## نصب",
                    "## نخستین گردش کار",
                    "## ایمنی انتشار",
                ),
            ),
            DocumentationRequirement(
                language="en",
                path=(
                    "docs/example-project.en.md"
                ),
                required_sections=(
                    "# Example project",
                    "## Structure",
                    "## Run",
                    "## Expected evidence",
                ),
            ),
            DocumentationRequirement(
                language="fa",
                path=(
                    "docs/example-project.fa.md"
                ),
                required_sections=(
                    "# پروژه نمونه",
                    "## ساختار",
                    "## اجرا",
                    "## شواهد مورد انتظار",
                ),
            ),
        ),
        example_root=(
            "examples/v1-sample-project"
        ),
        example_required_files=(
            "AGENTS.md",
            "README.md",
            "task-contract.json",
            "runtime-manifest.json",
            "input/customer-request.md",
        ),
    )


def require_documentation_ready(
    evidence: DocumentationEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    blockers: list[str] = []

    for item in evidence.documentation:
        if not item.passed:
            blockers.append(item.path)

    if not evidence.example_project.passed:
        blockers.append(
            evidence.example_project.root
        )

    raise RuntimeError(
        "Documentation validation failed: "
        + ", ".join(blockers)
    )
