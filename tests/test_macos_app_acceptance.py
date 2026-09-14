from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


acceptance = load_script("run_macos_app_acceptance")
builder = load_script("build_macos_app")


def test_spec_versions_come_from_packaged_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "1.2.39"\n')
    spec = builder.write_app_spec(source, tmp_path, "arm64", False).read_text()
    assert "'CFBundleShortVersionString': '1.2.39'" in spec
    assert "'CFBundleVersion': '1.2.39'" in spec
    assert "macos_app_entrypoint.py" in spec
    assert "macos_clean_app_entrypoint.py" not in spec


def test_recovery_double_runs_real_node_checks_for_two_tickets(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual fixture verification")
    fixture = acceptance.build_fixture_zip(tmp_path / "fixture.zip")
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(tmp_path / "project")
    root = tmp_path / "project" / "holda-acceptance"
    codex = acceptance.write_fake_codex(tmp_path / "bin", "recovery")
    for ticket in acceptance.TICKETS:
        failures = []
        for attempt in range(3):
            subprocess.run(
                [str(codex), "exec", "--cd", str(root), "--output-last-message", str(tmp_path / "last.txt")],
                input=ticket, text=True, check=True, capture_output=True,
            )
            verified = subprocess.run([node, "verify.mjs"], cwd=root, text=True, capture_output=True, check=False)
            if attempt < 2:
                assert verified.returncode != 0
                failures.append(verified.stderr)
            else:
                assert verified.returncode == 0
                assert "acceptance marker verified" in verified.stdout
        assert failures[0] != failures[1]
    assert acceptance.SECOND_MARKER in (root / "public_html/index.html").read_text()


def test_success_assertion_rejects_missing_or_failed_evidence() -> None:
    valid = {"run_status": "completed", "verification": {
        "status": "pass", "finalized_at": "2026-01-01", "diagnostics": [],
        "results": [{"status": "pass", "returncode": 0, "stdout": "acceptance marker verified"}],
    }}
    acceptance.assert_verification(valid)
    for key, value in (("status", "fail"), ("results", []), ("finalized_at", None)):
        invalid = json.loads(json.dumps(valid))
        invalid["verification"][key] = value
        with pytest.raises(AssertionError):
            acceptance.assert_verification(invalid)
