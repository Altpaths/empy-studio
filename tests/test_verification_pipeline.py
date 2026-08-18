from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from empy_studio.core.project_service import DefaultProjectService
from empy_studio.verification_pipeline import (
    VerificationCancelled,
    VerificationReport,
    VerificationRuntime,
    finalize_verification,
    map_project_verification,
    verification_contract_signature,
    verification_preflight,
    verification_staleness_reason,
)


def test_python_project_mapping_has_required_panels(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    detection = DefaultProjectService().detect(tmp_path)
    checks = map_project_verification(detection)
    assert {item.category for item in checks} == {"tests", "build", "lint"}


def test_plain_php_composer_mapping_keeps_test_contract_visible_without_dependencies(
    tmp_path: Path,
) -> None:
    (tmp_path / "composer.json").write_text(
        '{"name":"demo/php-app","require":{"example/package":"1.0"},'
        '"scripts":{"test":"php tests/run.php"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    detection = DefaultProjectService().detect(tmp_path)
    checks = map_project_verification(detection)

    assert detection.descriptor.project_type == "php"
    assert [item.check_id for item in checks] == ["build", "tests"]
    assert checks[0].command == ("composer", "validate", "--no-check-publish")
    assert checks[1].command == (
        "composer",
        "--no-interaction",
        "run-script",
        "test",
    )


def test_verification_preflight_surfaces_missing_composer_dependencies_before_run(
    tmp_path: Path,
) -> None:
    (tmp_path / "composer.json").write_text(
        '{"name":"demo/php-app","require":{"example/package":"1.0"},'
        '"scripts":{"test":"php tests/run.php"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "composer.lock").write_text("{}\n", encoding="utf-8")
    (tmp_path / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    preflight = verification_preflight(DefaultProjectService().detect(tmp_path))

    assert preflight.ready is False
    assert preflight.checks


def test_nested_composer_project_maps_real_test_script(tmp_path: Path) -> None:
    public_html = tmp_path / "public_html"
    public_html.mkdir()
    (public_html / "composer.json").write_text(
        '{"name":"demo/nested-site","scripts":{"test":"php tests/site-audit.php"}}\n',
        encoding="utf-8",
    )
    (public_html / "vendor").mkdir()
    (public_html / "vendor" / "autoload.php").write_text("<?php\n", encoding="utf-8")
    (public_html / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    detection = DefaultProjectService().detect(tmp_path)

    checks = map_project_verification(detection)

    assert detection.effective_verification_root == public_html.resolve()
    assert [item.check_id for item in checks] == ["build", "tests"]
    assert checks[1].command == (
        "composer",
        "--no-interaction",
        "run-script",
        "test",
    )


def test_persisted_verification_evidence_requires_current_contract(tmp_path: Path) -> None:
    (tmp_path / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    detection = DefaultProjectService().detect(tmp_path)
    report = VerificationReport(
        schema_version=1,
        verification_id="old-report",
        project_root=str(detection.descriptor.root),
        project_type=detection.descriptor.project_type,
        status="pass",
        started_at="now",
        finished_at="now",
        results=(),
        evidence_path=str(tmp_path / "evidence"),
        finalized_at="now",
    )

    assert verification_staleness_reason(report, detection) is not None
    current = VerificationReport(
        **{
            **report.__dict__,
            "contract_signature": verification_contract_signature(detection),
        }
    )
    assert verification_staleness_reason(current, detection) is None


def test_plain_php_without_composer_maps_safe_syntax_checks(tmp_path: Path) -> None:
    (tmp_path / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    (tmp_path / "admin").mkdir()
    (tmp_path / "admin" / "dashboard.php").write_text("<?php echo 'dashboard';\n", encoding="utf-8")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "dependency.php").write_text("<?php this is not linted;\n", encoding="utf-8")

    detection = DefaultProjectService().detect(tmp_path)
    checks = map_project_verification(detection)

    assert detection.descriptor.project_type == "php"
    assert [item.category for item in checks] == ["lint", "lint"]
    assert [item.label for item in checks] == [
        "PHP syntax · admin/dashboard.php",
        "PHP syntax · index.php",
    ]
    assert all(item.command[:2] == ("php", "-l") for item in checks)


def test_project_without_safe_checks_returns_actionable_failure_report(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")

    report = VerificationRuntime().run(
        detection=DefaultProjectService().detect(tmp_path),
        evidence_root=tmp_path / "evidence",
    )

    assert report.status == "fail"
    assert report.results == ()
    assert report.finalize_allowed is False
    assert report.diagnostics
    evidence = tmp_path / "evidence" / report.verification_id / "verification-report.json"
    saved = json.loads(evidence.read_text(encoding="utf-8"))
    assert saved["diagnostics"] == list(report.diagnostics)


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP CLI is not installed")
def test_plain_php_lint_runtime_can_finalize(tmp_path: Path) -> None:
    (tmp_path / "admin.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    report = VerificationRuntime().run(
        detection=DefaultProjectService().detect(tmp_path),
        evidence_root=tmp_path / "evidence",
    )

    assert report.status == "pass"
    assert [item.status for item in report.results] == ["pass"]
    assert finalize_verification(report).finalized_at is not None


def test_missing_verification_executable_is_recorded_as_failure(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    manifest = tmp_path / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "missing-tool",
                        "label": "missing tool",
                        "category": "tests",
                        "command": ["empy-command-that-does-not-exist"],
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

    assert report.status == "fail"
    assert report.results[0].returncode == 127
    assert "Unable to start verification command" in report.results[0].stderr
    assert not report.finalize_allowed


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


def test_verification_cancellation_terminates_blocking_check(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    manifest = tmp_path / ".empy" / "verification.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "blocking",
                        "label": "blocking check",
                        "category": "tests",
                        "command": [sys.executable, "-c", "import time; time.sleep(30)"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            VerificationRuntime().run(
                detection=DefaultProjectService().detect(tmp_path),
                evidence_root=tmp_path / "evidence",
                cancel_event=cancel_event,
                timeout_seconds=10,
            )
        except BaseException as exc:  # noqa: BLE001 - assert the worker terminates with the mapped error.
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.2)
    cancel_event.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VerificationCancelled)

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
