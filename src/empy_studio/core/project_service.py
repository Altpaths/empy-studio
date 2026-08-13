from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .contracts import ProjectDescriptor

IGNORED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".idea",
        ".vscode",
        ".venv",
        "node_modules",
        "vendor",
        "__pycache__",
    }
)


@dataclass(frozen=True)
class ProjectDetection:
    descriptor: ProjectDescriptor
    markers: tuple[str, ...]
    has_git: bool
    has_tests: bool
    package_manager: str | None
    verification_root: Path | None = None

    @property
    def effective_verification_root(self) -> Path:
        """Return the directory that owns the executable project contract.

        Imported archives often contain a deployment wrapper around the real
        application, for example ``site/public_html``.  The descriptor
        must continue to point at the wrapper so exports preserve the archive
        layout, while verification must run from the directory containing the
        manifest and its scripts.
        """

        return self.verification_root or self.descriptor.root


class DefaultProjectService:
    """Detect supported project types without modifying the project."""

    def describe(
        self,
        project_root: str | Path,
    ) -> ProjectDescriptor:
        return self.detect(project_root).descriptor

    def detect(
        self,
        project_root: str | Path,
    ) -> ProjectDetection:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)

        project_type, markers = self._detect_type(root)
        verification_root = self._find_verification_root(root)
        if verification_root != root:
            relative = verification_root.relative_to(root).as_posix()
            markers = (*markers, f"verification-root:{relative}/")
        descriptor = ProjectDescriptor(
            root=root,
            project_type=project_type,
            display_name=root.name,
        )
        descriptor.validate()

        return ProjectDetection(
            descriptor=descriptor,
            markers=markers,
            has_git=(root / ".git").exists(),
            has_tests=self._has_tests(verification_root),
            package_manager=self._detect_package_manager(verification_root),
            verification_root=verification_root,
        )

    def _find_verification_root(self, root: Path) -> Path:
        """Find a conventional nested application root without flattening it."""

        if self._has_project_manifest(root):
            return root

        for name in ("public_html", "public", "www", "web"):
            candidate = root / name
            if candidate.is_dir() and self._has_project_manifest(candidate):
                return candidate

        return root

    @staticmethod
    def _has_project_manifest(root: Path) -> bool:
        return any(
            (root / name).is_file()
            for name in (
                "composer.json",
                "pyproject.toml",
                "package.json",
                "Cargo.toml",
                "go.mod",
                "artisan",
            )
        )

    def _detect_type(
        self,
        root: Path,
    ) -> tuple[str, tuple[str, ...]]:
        if (
            (root / "artisan").is_file()
            and (root / "composer.json").is_file()
        ):
            markers = [
                "artisan",
                "composer.json",
            ]
            if (root / "routes" / "web.php").is_file():
                markers.append("routes/web.php")
            if (root / "resources").is_dir():
                markers.append("resources/")
            return "laravel", tuple(markers)

        if self._has_php_sources(root):
            markers = ["php"]
            for marker in (
                "composer.json",
                "index.php",
                "src/",
                "app/",
                "public/",
                "public_html/",
                "tests/",
            ):
                if marker.endswith("/"):
                    exists = (root / marker.rstrip("/")).is_dir()
                else:
                    exists = (root / marker).is_file()
                if exists and marker not in markers:
                    markers.append(marker)
            return "php", tuple(markers)

        if (root / "pyproject.toml").is_file():
            markers = ["pyproject.toml"]
            if (root / "src").is_dir():
                markers.append("src/")
            if (root / "tests").is_dir():
                markers.append("tests/")
            return "python", tuple(markers)

        if (root / "package.json").is_file():
            markers = ["package.json"]
            if (root / "src").is_dir():
                markers.append("src/")
            return "node", tuple(markers)

        if (
            (root / "Cargo.toml").is_file()
            and (root / "src").is_dir()
        ):
            return "rust", ("Cargo.toml", "src/")

        if (
            (root / "go.mod").is_file()
            and any(root.glob("*.go"))
        ):
            return "go", ("go.mod",)

        return "generic", self._generic_markers(root)

    def _generic_markers(
        self,
        root: Path,
    ) -> tuple[str, ...]:
        markers: list[str] = []
        for name in (
            "README.md",
            "README.rst",
            "Makefile",
            "Dockerfile",
        ):
            if (root / name).exists():
                markers.append(name)
        return tuple(markers)

    def _has_php_sources(
        self,
        root: Path,
    ) -> bool:
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = [
                directory
                for directory in directories
                if directory not in IGNORED_DIRECTORY_NAMES
                and not (Path(current) / directory).is_symlink()
            ]
            if any(filename.lower().endswith(".php") for filename in files):
                return True
        return False

    def _has_tests(
        self,
        root: Path,
    ) -> bool:
        return any(
            (root / name).exists()
            for name in (
                "tests",
                "test",
                "spec",
                "__tests__",
                "phpunit.xml",
                "phpunit.xml.dist",
            )
        )

    def _detect_package_manager(
        self,
        root: Path,
    ) -> str | None:
        checks = (
            ("composer.lock", "Composer"),
            ("uv.lock", "uv"),
            ("poetry.lock", "Poetry"),
            ("Pipfile.lock", "Pipenv"),
            ("requirements.txt", "pip"),
            ("pnpm-lock.yaml", "pnpm"),
            ("yarn.lock", "Yarn"),
            ("package-lock.json", "npm"),
            ("Cargo.lock", "Cargo"),
            ("go.sum", "Go modules"),
        )
        for marker, name in checks:
            if (root / marker).exists():
                return name
        return None
