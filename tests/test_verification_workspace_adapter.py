from __future__ import annotations

import json
import sys
from pathlib import Path

from empy_studio.core.project_service import DefaultProjectService
from empy_studio.desktop.verification_workspace_adapter import VerificationWorkspaceAdapter
from empy_studio.verification_pipeline import VerificationRuntime


def test_verification_report_persists_and_finalizes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("demo", encoding="utf-8")
    manifest = project / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"checks": [{"id": "tests", "category": "tests", "command": [sys.executable, "-c", "print('ok')"]}]}), encoding="utf-8")
    store = VerificationWorkspaceAdapter(tmp_path / "workspace")
    report = VerificationRuntime().run(detection=DefaultProjectService().detect(project), evidence_root=store.evidence_root)
    store.save(report)
    loaded = store.load(report.verification_id)
    assert loaded.results[0].stdout == "ok\n"
    finalized = store.finalize(report.verification_id)
    assert finalized.finalized_at is not None
