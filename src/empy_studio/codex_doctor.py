from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .codex_materializer import load_materialized_manifest
from .codex_preflight import detect_codex_host_diagnostic
from .codex_workflow import CodexRunManifest

DEFAULT_COMMAND_TIMEOUT = 10.0


@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    status: str
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Command timed out after {timeout_seconds} seconds: "
            f"{' '.join(command)}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Unable to execute command: {' '.join(command)}: {exc}"
        ) from exc


def _result(
    check_id: str,
    passed: bool,
    message: str,
    **details: Any,
) -> DoctorCheck:
    return DoctorCheck(
        check_id=check_id,
        status="passed" if passed else "failed",
        message=message,
        details=details,
    )


def _warning(
    check_id: str,
    message: str,
    **details: Any,
) -> DoctorCheck:
    return DoctorCheck(
        check_id=check_id,
        status="warning",
        message=message,
        details=details,
    )


def _host_diagnostic_details(
    stdout: str,
    stderr: str,
) -> dict[str, str]:
    diagnostic = detect_codex_host_diagnostic(stdout, stderr)
    if diagnostic is None:
        return {}
    return {
        "host_diagnostic": diagnostic.code,
        "host_message": diagnostic.message,
        "host_remediation": diagnostic.remediation,
    }


def _check_codex_executable(
    executable: str,
) -> tuple[DoctorCheck, str | None]:
    resolved = shutil.which(executable)

    if resolved is None:
        return (
            _result(
                "codex_executable",
                False,
                f"Codex executable was not found in PATH: {executable}",
            ),
            None,
        )

    return (
        _result(
            "codex_executable",
            True,
            "Codex executable is available",
            executable=resolved,
        ),
        resolved,
    )


def _check_codex_version(
    executable: str,
) -> DoctorCheck:
    result = _run_command([executable, "--version"])
    output = (result.stdout or result.stderr).strip()

    return _result(
        "codex_version",
        result.returncode == 0,
        (
            "Codex version command succeeded"
            if result.returncode == 0
            else "Codex version command failed"
        ),
        returncode=result.returncode,
        version=output,
        **_host_diagnostic_details(
            result.stdout or "",
            result.stderr or "",
        ),
    )


def _check_codex_exec(
    executable: str,
) -> DoctorCheck:
    result = _run_command(
        [executable, "exec", "--help"]
    )
    combined = (
        f"{result.stdout}\n"
        f"{result.stderr}"
    )

    passed = (
        result.returncode == 0
        and "exec" in combined.lower()
    )

    return _result(
        "codex_exec",
        passed,
        (
            "Codex non-interactive execution is available"
            if passed
            else "Codex exec is unavailable"
        ),
        returncode=result.returncode,
        **_host_diagnostic_details(
            result.stdout or "",
            result.stderr or "",
        ),
    )


def _check_codex_authentication(
    executable: str,
) -> DoctorCheck:
    result = _run_command(
        [executable, "login", "status"]
    )
    output = (result.stdout or result.stderr).strip()

    if result.returncode == 0:
        return _result(
            "codex_authentication",
            True,
            "Codex authentication is available",
            authentication_status=output,
            **_host_diagnostic_details(
                result.stdout or "",
                result.stderr or "",
            ),
        )

    return _result(
        "codex_authentication",
        False,
        "Codex is not authenticated",
        returncode=result.returncode,
        authentication_status=output,
        remediation="Run `codex login` and complete authentication.",
        **_host_diagnostic_details(
            result.stdout or "",
            result.stderr or "",
        ),
    )


def _check_project_root(
    manifest: CodexRunManifest,
) -> DoctorCheck:
    root = Path(manifest.project_root)

    if not root.is_dir():
        return _result(
            "project_root",
            False,
            "Project root does not exist",
            project_root=str(root),
        )

    return _result(
        "project_root",
        True,
        "Project root exists",
        project_root=str(root),
    )


def _check_materialized_run(
    manifest: CodexRunManifest,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    expected_paths = {
        "agents_file": manifest.agents_file,
        "prompt_file": manifest.prompt_file,
        "evidence_dir": manifest.evidence_dir,
    }

    for check_id, raw_path in expected_paths.items():
        if raw_path is None:
            checks.append(
                _result(
                    check_id,
                    False,
                    f"{check_id} is not declared in the Run Manifest",
                )
            )
            continue

        path = Path(raw_path)
        expected_exists = (
            path.is_dir()
            if check_id == "evidence_dir"
            else path.is_file()
        )

        checks.append(
            _result(
                check_id,
                expected_exists,
                (
                    f"{check_id} is available"
                    if expected_exists
                    else f"{check_id} is missing"
                ),
                path=str(path),
            )
        )

    return checks


def _check_git_repository(
    manifest: CodexRunManifest,
) -> list[DoctorCheck]:
    project_root = Path(manifest.project_root)

    result = _run_command(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_root,
    )

    if result.returncode != 0:
        return [
            _warning(
                "git_repository",
                "Project root is not a Git repository",
                returncode=result.returncode,
            )
        ]

    repository_root = result.stdout.strip()
    status = _run_command(
        ["git", "status", "--porcelain"],
        cwd=project_root,
    )

    checks = [
        _result(
            "git_repository",
            True,
            "Git repository is available",
            repository_root=repository_root,
        )
    ]

    if status.returncode != 0:
        checks.append(
            _warning(
                "git_worktree",
                "Unable to inspect Git working tree",
                returncode=status.returncode,
            )
        )
    elif status.stdout.strip():
        checks.append(
            _warning(
                "git_worktree",
                "Git working tree contains uncommitted changes",
                changed_entry_count=len(
                    status.stdout.strip().splitlines()
                ),
            )
        )
    else:
        checks.append(
            _result(
                "git_worktree",
                True,
                "Git working tree is clean",
            )
        )

    return checks


def diagnose_codex_environment(
    manifest_path: str | Path,
    *,
    codex_executable: str = "codex",
    command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT,
) -> dict[str, Any]:
    if command_timeout_seconds <= 0:
        raise ValueError(
            "command_timeout_seconds must be greater than zero"
        )

    global DEFAULT_COMMAND_TIMEOUT
    previous_timeout = DEFAULT_COMMAND_TIMEOUT
    DEFAULT_COMMAND_TIMEOUT = command_timeout_seconds

    try:
        manifest = load_materialized_manifest(
            manifest_path
        )
        checks: list[DoctorCheck] = []

        executable_check, resolved_executable = (
            _check_codex_executable(codex_executable)
        )
        checks.append(executable_check)

        if resolved_executable is not None:
            checks.extend(
                [
                    _check_codex_version(
                        resolved_executable
                    ),
                    _check_codex_exec(
                        resolved_executable
                    ),
                    _check_codex_authentication(
                        resolved_executable
                    ),
                ]
            )
            host_checks = [
                check
                for check in checks
                if check.details.get("host_diagnostic")
            ]
            if host_checks:
                source = host_checks[0]
                checks.append(
                    _result(
                        "codex_host_preflight",
                        False,
                        str(
                            source.details.get(
                                "host_message",
                                "Codex host preflight is not ready.",
                            )
                        ),
                        diagnostic=source.details.get("host_diagnostic"),
                        remediation=source.details.get(
                            "host_remediation",
                            "Refresh the environment after fixing the host issue.",
                        ),
                    )
                )

        checks.append(_check_project_root(manifest))
        checks.extend(_check_materialized_run(manifest))

        if Path(manifest.project_root).is_dir():
            checks.extend(_check_git_repository(manifest))

        failed = [
            check
            for check in checks
            if check.status == "failed"
        ]
        warnings = [
            check
            for check in checks
            if check.status == "warning"
        ]

        return {
            "status": (
                "ready"
                if not failed
                else "not_ready"
            ),
            "run_id": manifest.run_id,
            "failed_check_count": len(failed),
            "warning_count": len(warnings),
            "checks": [
                check.to_dict()
                for check in checks
            ],
        }
    finally:
        DEFAULT_COMMAND_TIMEOUT = previous_timeout
