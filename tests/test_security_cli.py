from __future__ import annotations

from pathlib import Path

from empy_studio.cli import build_parser
from empy_studio.security_cli import security_audit_command


def test_security_audit_parser() -> None:
    args = build_parser().parse_args(
        [
            "security",
            "audit",
            "--project-root",
            "/tmp/project",
            "--evidence",
            "/tmp/security.json",
        ]
    )

    assert args.command == "security"
    assert args.security_command == "audit"
    assert args.source_directory == "src"


def test_security_audit_command_returns_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeEvidence:
        def to_dict(self) -> dict[str, object]:
            return {
                "schema_version": 1,
                "status": "passed",
            }

    def fake_run(config):
        captured["project_root"] = config.project_root
        captured["evidence_path"] = config.evidence_path
        captured["python_executable"] = config.python_executable
        captured["source_directory"] = config.source_directory
        return FakeEvidence()

    monkeypatch.setattr(
        "empy_studio.security_cli.run_security_audit",
        fake_run,
    )

    result = security_audit_command(
        str(tmp_path / "project"),
        str(tmp_path / "security.json"),
        python_executable="python-custom",
        source_directory="package",
    )

    assert result["status"] == "passed"
    assert captured == {
        "project_root": str(tmp_path / "project"),
        "evidence_path": str(tmp_path / "security.json"),
        "python_executable": "python-custom",
        "source_directory": "package",
    }
