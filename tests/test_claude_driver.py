from __future__ import annotations

import json
import os
from pathlib import Path

from empy_studio.core import DriverExecutionRequest, ProjectDescriptor
from empy_studio.drivers import ClaudeCodeDriver


def fake_claude_cli(tmp_path: Path) -> Path:
    executable = tmp_path / "claude-fake"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import pathlib\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('claude-code-test 1.0')\n"
        "    raise SystemExit(0)\n"
        "pathlib.Path.cwd().joinpath('changed.txt').write_text('ok\\n')\n"
        "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'done'}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_claude_driver_reports_missing_external_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = fake_claude_cli(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    inspection = ClaudeCodeDriver(executable=str(executable)).inspect()

    assert inspection.availability == "unauthenticated"
    assert inspection.ready is False
    assert "ANTHROPIC_API_KEY" in (inspection.remediation or "")
    assert "secret" not in json.dumps(inspection.to_dict())


def test_claude_driver_executes_bounded_cli_without_persisting_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = fake_claude_cli(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret-never-written")
    project_root = tmp_path / "project"
    project_root.mkdir()
    descriptor = ProjectDescriptor(
        root=project_root,
        project_type="unknown",
        display_name="demo",
    )
    request = DriverExecutionRequest(
        project=descriptor,
        task_id="ticket-1",
        prompt="Update only changed.txt.",
        allowed_paths=("changed.txt",),
        timeout_seconds=10,
    )
    driver = ClaudeCodeDriver(executable=str(executable))

    result = driver.execute(request)

    assert result.status == "completed"
    assert result.return_code == 0
    assert (project_root / "changed.txt").read_text(encoding="utf-8") == "ok\n"
    assert "test-secret-never-written" not in str(result)
    assert "ANTHROPIC_API_KEY" in os.environ
