from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from empy_studio.core.project_service import DefaultProjectService
from empy_studio.verification_pipeline import (
    VerificationRuntime,
    finalize_verification,
    map_project_verification,
)


def test_python_project_mapping_has_required_panels(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    detection = DefaultProjectService().detect(tmp_path)
    checks = map_project_verification(detection)
    assert {item.category for item in checks} == {"tests", "build", "lint"}


def test_manifest_commands_stream_and_failure_blocks_finalize(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    manifest = tmp_path / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "tests",
                        "label": "real test",
                        "category": "tests",
                        "command": [sys.executable, "-c", "import sys; print('visible-out'); print('visible-err', file=sys.stderr); raise SystemExit(2)"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    detection = DefaultProjectService().detect(tmp_path)
    events = []
    report = VerificationRuntime().run(
        detection=detection,
        evidence_root=tmp_path / "evidence",
        on_event=events.append,
    )
    assert report.status == "fail"
    assert any("visible-out" in event.text and event.stream == "stdout" for event in events)
    assert any("visible-err" in event.text and event.stream == "stderr" for event in events)
    assert not report.finalize_allowed
    with pytest.raises(RuntimeError, match="before Finalize"):
        finalize_verification(report)


def test_passing_report_can_finalize(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    manifest = tmp_path / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "tests",
                        "label": "passing",
                        "category": "tests",
                        "command": [sys.executable, "-c", "print('ok')"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = VerificationRuntime().run(
        detection=DefaultProjectService().detect(tmp_path),
        evidence_root=tmp_path / "evidence",
    )
    finalized = finalize_verification(report)
    assert finalized.finalized_at is not None

def test_manifest_rejects_unknown_category(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    manifest = tmp_path / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "security",
                        "label": "unsupported",
                        "category": "security",
                        "command": [sys.executable, "-c", "print('no-op')"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    detection = DefaultProjectService().detect(tmp_path)
    with pytest.raises(ValueError, match="tests, build, or lint"):
        map_project_verification(detection)

