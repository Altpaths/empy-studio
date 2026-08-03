from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from empy_studio.quality_evidence import (
    QualityConfig,
    load_coverage_summary,
    require_quality_gate,
    run_quality_gate,
)


def project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='example'\n",
        encoding="utf-8",
    )
    source = root / "src" / "empy_studio"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(
        "def test_value(): assert True\n",
        encoding="utf-8",
    )
    return root


def completed(
    command: list[str],
    *,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout="ok",
        stderr="",
    )


def write_coverage(
    path: Path,
    percent: float,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": percent,
                    "covered_lines": 90,
                    "missing_lines": 10,
                    "num_statements": 100,
                }
            }
        ),
        encoding="utf-8",
    )


def test_quality_gate_passes(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    coverage_path = (
        tmp_path / "coverage.json"
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        if "json" in command:
            write_coverage(
                coverage_path,
                90.0,
            )
        return completed(command)

    evidence_path = (
        tmp_path / "quality.json"
    )
    evidence = run_quality_gate(
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                evidence_path
            ),
            coverage_json_path=str(
                coverage_path
            ),
            coverage_threshold=80.0,
        ),
        runner=runner,
    )

    assert evidence.status == "passed"
    assert evidence.coverage.percent_covered == 90.0
    assert evidence_path.is_file()
    assert [
        item.name
        for item in evidence.commands
    ] == [
        "ruff",
        "mypy",
        "coverage",
        "coverage_json",
    ]


def test_stops_after_failed_command(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    calls: list[str] = []

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        name = (
            "ruff"
            if "ruff" in command
            else "other"
        )
        calls.append(name)
        return completed(
            command,
            returncode=1,
        )

    evidence = run_quality_gate(
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "quality.json"
            ),
            coverage_json_path=str(
                tmp_path / "coverage.json"
            ),
        ),
        runner=runner,
    )

    assert evidence.status == "failed"
    assert len(evidence.commands) == 1
    assert evidence.failed_commands == (
        "ruff",
    )


def test_low_coverage_blocks_gate(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    coverage_path = (
        tmp_path / "coverage.json"
    )

    def runner(
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        if "json" in command:
            write_coverage(
                coverage_path,
                70.0,
            )
        return completed(command)

    evidence = run_quality_gate(
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "quality.json"
            ),
            coverage_json_path=str(
                coverage_path
            ),
            coverage_threshold=80.0,
        ),
        runner=runner,
    )

    assert evidence.status == "failed"
    assert evidence.coverage.passed is False


def test_loads_coverage_summary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "coverage.json"
    write_coverage(path, 88.5)

    summary = load_coverage_summary(
        path,
        threshold=80.0,
    )

    assert summary.percent_covered == 88.5
    assert summary.total_statements == 100
    assert summary.passed is True


def test_require_quality_gate_raises(
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
            returncode=1,
        )

    evidence = run_quality_gate(
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "quality.json"
            ),
            coverage_json_path=str(
                tmp_path / "coverage.json"
            ),
        ),
        runner=runner,
    )

    with pytest.raises(
        RuntimeError,
        match="ruff",
    ):
        require_quality_gate(
            evidence
        )


def test_rejects_unsafe_relative_path(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    with pytest.raises(
        ValueError,
        match="safe relative paths",
    ):
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "quality.json"
            ),
            coverage_json_path=str(
                tmp_path / "coverage.json"
            ),
            source_package="../outside",
        ).validate()


def test_rejects_invalid_threshold(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)

    with pytest.raises(
        ValueError,
        match="between 0 and 100",
    ):
        QualityConfig(
            project_root=str(root),
            evidence_path=str(
                tmp_path / "quality.json"
            ),
            coverage_json_path=str(
                tmp_path / "coverage.json"
            ),
            coverage_threshold=101.0,
        ).validate()
