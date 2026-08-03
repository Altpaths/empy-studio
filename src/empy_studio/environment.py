from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: str
    message: str
    recommendation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "recommendation": self.recommendation,
        }


def _run(command: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _tool_check(name: str, args: Sequence[str], recommendation: str) -> CheckResult:
    executable = shutil.which(name)
    if not executable:
        return CheckResult(name, "fail", f"{name} was not found.", recommendation)
    result = _run([executable, *args])
    output = (result.stdout or result.stderr).strip().splitlines()
    message = output[0] if output else f"{name} is available."
    return CheckResult(
        name,
        "pass" if result.returncode == 0 else "warn",
        message,
        None if result.returncode == 0 else recommendation,
    )


def doctor(project_root: str | Path = ".", vault_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checks: list[CheckResult] = []

    version = sys.version_info[:3]
    if version >= MIN_PYTHON:
        checks.append(CheckResult("python", "pass", f"Python {version[0]}.{version[1]}.{version[2]}"))
    else:
        checks.append(
            CheckResult(
                "python",
                "fail",
                f"Python {version[0]}.{version[1]}.{version[2]} is below the required 3.10.",
                "Install Python 3.12 and run Empy Studio with that interpreter.",
            )
        )

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    checks.append(
        CheckResult(
            "virtual_environment",
            "pass" if in_venv else "warn",
            f"Active environment: {sys.prefix}" if in_venv else "No active virtual environment detected.",
            None if in_venv else "Run `empy bootstrap` or activate `.venv`.",
        )
    )

    checks.append(_tool_check("git", ["--version"], "Install Git before using repository workflows."))
    gh = shutil.which("gh")
    if gh:
        checks.append(_tool_check("gh", ["--version"], "Reinstall GitHub CLI."))
    else:
        checks.append(
            CheckResult(
                "gh",
                "warn",
                "GitHub CLI was not found.",
                "Install GitHub CLI only if GitHub integration is required.",
            )
        )

    if gh:
        auth = _run([gh, "auth", "status"])
        checks.append(
            CheckResult(
                "github_auth",
                "pass" if auth.returncode == 0 else "warn",
                (
                    "GitHub CLI authentication is active."
                    if auth.returncode == 0
                    else "GitHub CLI is not authenticated."
                ),
                None if auth.returncode == 0 else "Run `gh auth login`.",
            )
        )

    git_dir = root / ".git"
    checks.append(
        CheckResult(
            "git_repository",
            "pass" if git_dir.exists() else "warn",
            (
                f"Git repository detected at {root}."
                if git_dir.exists()
                else "Current directory is not a Git repository."
            ),
            None if git_dir.exists() else "Run the command from a project repository.",
        )
    )

    pyproject = root / "pyproject.toml"
    checks.append(
        CheckResult(
            "project_metadata",
            "pass" if pyproject.exists() else "warn",
            "pyproject.toml is present." if pyproject.exists() else "pyproject.toml was not found.",
            (
                None
                if pyproject.exists()
                else "Run from the Empy Studio source directory or install the package."
            ),
        )
    )

    ci = root / ".github" / "workflows" / "ci.yml"
    checks.append(
        CheckResult(
            "ci_workflow",
            "pass" if ci.exists() else "warn",
            (
                "GitHub Actions CI workflow is configured."
                if ci.exists()
                else "GitHub Actions CI workflow was not found."
            ),
            None if ci.exists() else "Add a CI workflow before publishing releases.",
        )
    )

    if vault_root:
        vault = Path(vault_root).resolve()
        manifest = vault / "baseline" / "manifest.json"
        vault_metadata = vault / "vault.json"
        checks.append(
            CheckResult(
                "project_vault",
                "pass" if manifest.exists() and vault_metadata.exists() else "fail",
                (
                    f"Project Vault found at {vault}."
                    if manifest.exists() and vault_metadata.exists()
                    else f"Project Vault is incomplete at {vault}."
                ),
                None if manifest.exists() and vault_metadata.exists() else "Run `empy vault init`.",
            )
        )

    passed = sum(item.status == "pass" for item in checks)
    warned = sum(item.status == "warn" for item in checks)
    failed = sum(item.status == "fail" for item in checks)
    score = round((passed + warned * 0.5) / len(checks) * 100) if checks else 0
    status = "healthy" if failed == 0 and warned == 0 else ("attention" if failed == 0 else "blocked")
    return {
        "engine": "environment_doctor",
        "status": status,
        "health_score": score,
        "summary": {"pass": passed, "warn": warned, "fail": failed},
        "checks": [item.as_dict() for item in checks],
    }


def _python_version(executable: str) -> tuple[int, int, int] | None:
    result = _run([executable, "-c", "import json,sys; print(json.dumps(list(sys.version_info[:3])))"])
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout)
        return int(raw[0]), int(raw[1]), int(raw[2])
    except (ValueError, TypeError, json.JSONDecodeError, IndexError):
        return None


def select_python(candidates: Sequence[str] | None = None) -> str:
    names = list(candidates or ["python3.13", "python3.12", "python3.11", "python3.10", "python3"])
    for name in names:
        executable = shutil.which(name)
        if executable and (_python_version(executable) or (0, 0, 0)) >= MIN_PYTHON:
            return executable
    if sys.version_info[:2] >= MIN_PYTHON:
        return sys.executable
    raise RuntimeError("Python 3.10 or newer was not found.")


def bootstrap(
    project_root: str | Path = ".",
    venv_dir: str | Path = ".venv",
    include_dev: bool = False,
    python_executable: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    target = Path(venv_dir)
    if not target.is_absolute():
        target = root / target
    interpreter = python_executable or select_python()
    commands: list[list[str]] = [[interpreter, "-m", "venv", str(target)]]

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    env_python = target / bin_dir / ("python.exe" if os.name == "nt" else "python")
    spec = ".[dev]" if include_dev else "."
    commands.extend(
        [
            [str(env_python), "-m", "pip", "install", "--upgrade", "pip"],
            [str(env_python), "-m", "pip", "install", "-e", spec],
        ]
    )

    if dry_run:
        return {
            "engine": "bootstrap",
            "status": "planned",
            "python": interpreter,
            "venv": str(target),
            "commands": commands,
        }

    results: list[dict[str, Any]] = []
    for command in commands:
        result = _run(command, cwd=root)
        results.append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
            }
        )
        if result.returncode != 0:
            return {
                "engine": "bootstrap",
                "status": "failed",
                "python": interpreter,
                "venv": str(target),
                "results": results,
            }
    return {
        "engine": "bootstrap",
        "status": "ready",
        "python": interpreter,
        "venv": str(target),
        "activation": str(target / bin_dir / ("activate" if os.name != "nt" else "activate.bat")),
        "results": results,
    }


def validate(project_root: str | Path = ".", fix: bool = False) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checks: list[tuple[str, list[str]]] = []
    if fix:
        checks.append(("ruff_fix", [sys.executable, "-m", "ruff", "check", ".", "--fix"]))
    checks.extend(
        [
            ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
            ("mypy", [sys.executable, "-m", "mypy", "src"]),
            ("pytest", [sys.executable, "-m", "pytest", "-q"]),
        ]
    )
    results: list[dict[str, Any]] = []
    for name, command in checks:
        result = _run(command, cwd=root)
        results.append(
            {
                "id": name,
                "status": "pass" if result.returncode == 0 else "fail",
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        )
        if result.returncode != 0:
            return {"engine": "validation", "status": "failed", "results": results}
    return {"engine": "validation", "status": "pass", "results": results}
