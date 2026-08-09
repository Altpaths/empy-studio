from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from empy_studio.security_audit import (
    SecurityAuditConfig,
    load_declared_dependencies,
    require_security_audit,
    run_security_audit,
)


def project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "project"
    root.mkdir()

    (root / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "1.0.0"
dependencies = [
  "requests>=2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    source = root / "src" / "example"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    return root


def completed(
    command: list[str],
    returncode: int = 0,
    stdout: str = "[]",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_loads_declared_dependencies(
    tmp_path: Path,
) -> None:
    records = load_declared_dependencies(
        project(tmp_path)
    )

    assert {
        record.name
        for record in records
    } == {
        "requests",
        "pytest",
    }


def test_redacts_dependency_url_credentials(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (root / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "1.0.0"
dependencies = [
  "private-package @ https://build-user:build-password@example.test/private.whl",
]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    records = load_declared_dependencies(root)

    assert "build-password" not in records[0].specifier
    assert "<redacted>" in records[0].specifier


def test_clean_project_passes(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    assert evidence.status == "passed"
    assert evidence.blocking_findings == ()
    assert len(evidence.commands) == 2


def test_detects_embedded_secret(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "src"
        / "example"
        / "secret.py"
    ).write_text(
        'api_key = "abcdefghijklmnop"\n',
        encoding="utf-8",
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    assert evidence.status == "failed"
    assert any(
        item.rule_id
        == "secret.generic_assignment"
        for item in evidence.findings
    )


def test_detects_eval(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "src"
        / "example"
        / "dynamic.py"
    ).write_text(
        "def run(value: str):\n"
        "    return eval(value)\n",
        encoding="utf-8",
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    assert any(
        item.rule_id
        == "source.dynamic_execution"
        for item in evidence.findings
    )


def test_detects_subprocess_shell_true(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "src"
        / "example"
        / "shell.py"
    ).write_text(
        "import subprocess\n"
        "subprocess.run('echo ok', shell=True)\n",
        encoding="utf-8",
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    assert any(
        item.rule_id
        == "source.subprocess_shell_true"
        for item in evidence.findings
    )


def test_pip_check_failure_blocks(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        if "check" in command:
            return completed(
                command,
                returncode=1,
                stderr="broken dependency",
            )
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    assert evidence.status == "failed"
    assert any(
        item.rule_id
        == "dependency.pip_check_failed"
        for item in evidence.findings
    )


def test_require_security_audit_raises(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    (
        root
        / "src"
        / "example"
        / "dynamic.py"
    ).write_text(
        "eval('1 + 1')\n",
        encoding="utf-8",
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command)

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    with pytest.raises(
        RuntimeError,
        match="source.dynamic_execution",
    ):
        require_security_audit(
            evidence
        )


def test_rejects_source_escape(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    with pytest.raises(
        ValueError,
        match="escapes",
    ):
        run_security_audit(
            SecurityAuditConfig(
                project_root=str(root),
                evidence_path=str(
                    tmp_path / "security.json"
                ),
                source_directory="../outside",
            ),
            runner=lambda command, cwd: completed(
                command
            ),
        )


def test_redacts_sensitive_command_output(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            stdout=(
                'TOKEN = "abcdefghijklmnop"\n'
                "ghp_" + "A" * 24
            ),
            stderr='password="another-secret-value"',
        )

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=runner,
    )

    serialized = json.dumps(evidence.to_dict())
    assert "abcdefghijklmnop" not in serialized
    assert "another-secret-value" not in serialized
    assert "<redacted>" in serialized


def test_skips_symlinked_secret_file(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    outside = tmp_path / "outside-secret.py"
    outside.write_text(
        'api_key = "abcdefghijklmnop"\n',
        encoding="utf-8",
    )
    link = root / "src" / "example" / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    evidence = run_security_audit(
        SecurityAuditConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "security.json"
            ),
        ),
        runner=lambda command, cwd: completed(
            command
        ),
    )

    assert not any(
        item.path == "src/example/linked.py"
        for item in evidence.findings
    )


def test_rejects_symlinked_source_directory(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    shutil.rmtree(root / "src")
    outside = tmp_path / "outside-src"
    outside.mkdir()
    (outside / "example").mkdir()
    try:
        (root / "src").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(
        ValueError,
        match="source_directory cannot contain symlinks",
    ):
        run_security_audit(
            SecurityAuditConfig(
                project_root=str(root),
                evidence_path=str(
                    tmp_path / "security.json"
                ),
            ),
            runner=lambda command, cwd: completed(
                command
            ),
        )
