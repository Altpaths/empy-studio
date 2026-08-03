from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except (FileNotFoundError, PermissionError) as exc:
        return {
            "command": command,
            "returncode": None,
            "status": "fail",
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": command,
        "returncode": result.returncode,
        "status": "pass" if result.returncode == 0 else "fail",
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def evaluate_done(
    project_root: str | Path = ".",
    *,
    require_clean_git: bool = True,
    require_changelog: bool = True,
    require_docs: bool = True,
    require_tests: bool = True,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checks: list[dict[str, Any]] = []

    required_files = ["pyproject.toml", "README.md", "EMPY.md", "AGENTS.md"]
    if require_changelog:
        required_files.append("CHANGELOG.md")

    missing = [name for name in required_files if not (root / name).exists()]
    checks.append({
        "id": "required_files",
        "status": "pass" if not missing else "fail",
        "missing": missing,
    })

    if require_docs:
        docs_ok = (root / "docs").is_dir() and any((root / "docs").glob("*.md"))
        checks.append({"id": "documentation", "status": "pass" if docs_ok else "fail"})

    if require_clean_git and (root / ".git").exists():
        git_check = _run(["git", "status", "--porcelain"], root)
        dirty = git_check["status"] == "pass" and bool(git_check["stdout"].strip())
        checks.append({
            "id": "clean_git",
            "status": "fail" if dirty or git_check["status"] == "fail" else "pass",
            "details": git_check["stdout"].splitlines(),
            "error": git_check["stderr"],
        })

    if require_tests:
        venv = root / ".venv" / "bin"
        checks.extend([
            {
                "id": "ruff",
                **_run([str(venv / "ruff") if (venv / "ruff").exists() else "ruff", "check", "."], root),
            },
            {
                "id": "mypy",
                **_run([str(venv / "mypy") if (venv / "mypy").exists() else "mypy", "src"], root),
            },
            {
                "id": "pytest",
                **_run(
                    [
                        str(venv / "python") if (venv / "python").exists() else "python3",
                        "-m",
                        "pytest",
                        "-q",
                    ],
                    root,
                ),
            },
        ])

    failed = [check["id"] for check in checks if check["status"] == "fail"]
    return {
        "engine": "definition_of_done",
        "project_root": str(root),
        "checks": checks,
        "failed": failed,
        "status": "pass" if not failed else "blocked",
    }
