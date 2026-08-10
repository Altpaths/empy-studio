from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from empy_studio.verification_pipeline import (
    VerificationCategory,
    VerificationCheck,
    VerificationReport,
    VerificationResult,
    VerificationResultStatus,
    VerificationStatus,
    finalize_verification,
)


class VerificationWorkspaceAdapter:
    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve() / "verification"
        self.root.mkdir(parents=True, exist_ok=True)
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir(parents=True, exist_ok=True)

    def save(self, report: VerificationReport) -> Path:
        destination = self.root / f"{report.verification_id}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load(self, verification_id: str) -> VerificationReport:
        value = json.loads((self.root / f"{verification_id}.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("verification report must be an object")
        raw_results = value.get("results", [])
        if not isinstance(raw_results, list):
            raise TypeError("verification results must be a list")
        results: list[VerificationResult] = []
        for raw in raw_results:
            if not isinstance(raw, dict) or not isinstance(raw.get("check"), dict):
                raise TypeError("invalid verification result")
            raw_check = cast(dict[str, object], raw["check"])
            raw_command = raw_check.get("command", [])
            if not isinstance(raw_command, list):
                raise TypeError("verification command must be a list")
            check = VerificationCheck(
                check_id=str(raw_check["check_id"]),
                label=str(raw_check["label"]),
                category=cast(VerificationCategory, str(raw_check["category"])),
                command=tuple(str(item) for item in raw_command),
            )
            results.append(
                VerificationResult(
                    check=check,
                    status=cast(VerificationResultStatus, str(raw["status"])),
                    returncode=int(cast(int | str, raw["returncode"])),
                    stdout=str(raw.get("stdout", "")),
                    stderr=str(raw.get("stderr", "")),
                    started_at=str(raw["started_at"]),
                    finished_at=str(raw["finished_at"]),
                )
            )
        return VerificationReport(
            schema_version=int(cast(int | str, value["schema_version"])),
            verification_id=str(value["verification_id"]),
            project_root=str(value["project_root"]),
            project_type=str(value["project_type"]),
            status=cast(VerificationStatus, str(value["status"])),
            started_at=str(value["started_at"]),
            finished_at=str(value["finished_at"]) if value.get("finished_at") is not None else None,
            results=tuple(results),
            evidence_path=str(value["evidence_path"]),
            finalized_at=str(value["finalized_at"]) if value.get("finalized_at") is not None else None,
            diagnostics=tuple(str(item) for item in value.get("diagnostics", []) if isinstance(item, str)),
        )

    def list_reports(self, project_root: str | None = None) -> tuple[VerificationReport, ...]:
        reports = [self.load(path.stem) for path in self.root.glob("*.json")]
        if project_root is not None:
            reports = [item for item in reports if item.project_root == project_root]
        reports.sort(key=lambda item: item.started_at, reverse=True)
        return tuple(reports)

    def finalize(self, verification_id: str) -> VerificationReport:
        report = finalize_verification(self.load(verification_id))
        self.save(report)
        return report
