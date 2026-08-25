from __future__ import annotations

import zipfile
from pathlib import Path

from empy_studio.core import (
    DefaultProjectService,
    DriverExecutionRequest,
    ProductTask,
    approve_execution_plan,
    build_agent_run_graph,
    build_context_selection,
    build_token_budget,
    generate_execution_plan,
    lock_token_budget,
)
from empy_studio.drivers import (
    CodexGraphRuntime,
    CodexInstallation,
    CodexNodeExecution,
)
from empy_studio.project_delivery import export_project_zip, import_project_folder
from empy_studio.vault import initialize_vault


def _plain_php_source(root: Path) -> None:
    public = root / "public_html"
    public.mkdir(parents=True)
    (public / "composer.json").write_text(
        '{"name":"fixture/result-flow"}\n',
        encoding="utf-8",
    )
    files = {
        "about.php": "<?php echo 'about';\n",
        "patrol.php": "<?php function patrol(): array { return []; }\n",
        "journey-report.php": "<?php function journeyReport(): array { return []; }\n",
        "completion.php": "<?php function completion(): array { return []; }\n",
        "analyze-financial-doc.php": "<?php function analyzeDocument(): array { return []; }\n",
    }
    for name, content in files.items():
        (public / name).write_text(content, encoding="utf-8")


def _task(root: Path) -> ProductTask:
    return ProductTask(
        task_id="result-driven-php",
        project_root=str(root.resolve()),
        kind="custom",
        title="اتصال به ای پی آی هوش مصنوعی",
        objective="اتصال به ای پی آی هوش مصنوعی و ساخت گزارش مقایسه در بخش پایش",
        requirements=(
            "گزارش پایش باید داده واقعی سرویس را نمایش دهد",
            "فایل‌های لازم را بساز و تغییر واقعی ایجاد کن",
        ),
        constraints=("هیچ کلید یا فایل محرمانه‌ای نساز",),
        definition_of_done=("تغییر واقعی و ZIP قابل استخراج تولید شود",),
        status="ready_for_planning",
    )


class _ResultDriver:
    def __init__(self, *, change_files: bool = True, pass_result: bool = True) -> None:
        self.change_files = change_files
        self.pass_result = pass_result
        self.requests: list[DriverExecutionRequest] = []

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        del refresh
        return CodexInstallation(
            availability="available",
            executable="/usr/local/bin/codex",
            version="codex-cli test",
            authenticated=True,
            message="ready",
        )

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress=None,
    ) -> CodexNodeExecution:
        del on_progress
        self.requests.append(request)
        changed: tuple[str, ...] = ()
        if self.change_files:
            report = request.project.root / "public_html" / "journey-report.php"
            report.write_text(
                "<?php function journeyReport(): array { return ['provider' => 'avalai']; }\n",
                encoding="utf-8",
            )
            service = request.project.root / "public_html" / "services" / "avalai-client.php"
            service.parent.mkdir(parents=True, exist_ok=True)
            service.write_text(
                "<?php function avalaiClient(): string { return getenv('AVALAI_API_URL') ?: ''; }\n",
                encoding="utf-8",
            )
            changed = (
                "public_html/journey-report.php",
                "public_html/services/avalai-client.php",
            )
        artifacts = Path(artifact_dir)
        summary = (
            "Implementation completed.\nEMPY_NODE_RESULT: PASS"
            if self.pass_result
            else "The objective could not be completed.\nEMPY_NODE_RESULT: FAIL"
        )
        return CodexNodeExecution(
            node_id=node_id,
            task_id=request.task_id,
            status="completed",
            started_at="2026-08-25T00:00:00+00:00",
            finished_at="2026-08-25T00:00:01+00:00",
            return_code=0,
            thread_id="fixture-thread",
            summary=summary,
            changed_files=changed,
            event_count=0,
            events_path=str(artifacts / "events.jsonl"),
            stderr_path=str(artifacts / "stderr.log"),
            final_message_path=str(artifacts / "final-message.md"),
            command_path=str(artifacts / "command.json"),
        )

    def cancel(self) -> None:
        return None


def _workflow(root: Path):
    detection = DefaultProjectService().detect(root)
    task = _task(root)
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=detection),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=detection, plan=plan)
    budget = lock_token_budget(build_token_budget(plan=plan, selection=selection))
    graph = build_agent_run_graph(plan=plan, selection=selection, budget=budget)
    return detection, task, plan, selection, budget, graph


def test_plain_php_ticket_uses_one_relevant_writer_and_directadmin_zip(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _plain_php_source(source)
    imported = import_project_folder(source, tmp_path / "workspace")
    vault = tmp_path / "vault"
    initialize_vault(
        project_root=imported.project_root,
        vault_root=vault,
        project_id="result-flow",
        project_name="fixture",
    )
    baseline = vault / "baseline" / "source.zip"
    detection, task, plan, selection, budget, graph = _workflow(imported.project_root)

    assert [step.suggested_agent for step in plan.steps] == ["backend"]
    pack = selection.packs[0]
    scores = {item.relative_path: item.score for item in pack.files}
    assert scores["public_html/journey-report.php"] > scores["public_html/about.php"]
    assert "public_html/" in graph.nodes[0].owned_files

    driver = _ResultDriver()
    result = CodexGraphRuntime(
        driver=driver,
        run_root=tmp_path / "runs",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
        task=task,
    )

    assert result.status == "completed"
    assert len(driver.requests) == 1
    assert driver.requests[0].fresh_token_limit == 24_000
    assert driver.requests[0].reasoning_effort == "none"
    exported = export_project_zip(
        imported.project_root,
        tmp_path / "out" / "directadmin.zip",
        baseline_snapshot=baseline,
    )
    assert exported.extraction_root == "."
    assert exported.changed_files == (
        "public_html/journey-report.php",
        "public_html/services/avalai-client.php",
    )
    with zipfile.ZipFile(exported.archive_path) as archive:
        assert archive.namelist() == list(exported.changed_files)


def test_writer_process_without_a_change_is_not_a_success(tmp_path: Path) -> None:
    _plain_php_source(tmp_path)
    detection, task, _plan, selection, budget, graph = _workflow(tmp_path)

    result = CodexGraphRuntime(
        driver=_ResultDriver(change_files=False),
        run_root=tmp_path / "runs",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
        task=task,
    )

    assert result.status == "failed"
    assert result.error_code == "objective_not_met"
    assert result.node_results[0].changed_files == ()


def test_agent_declared_failure_is_not_a_success(tmp_path: Path) -> None:
    _plain_php_source(tmp_path)
    detection, task, _plan, selection, budget, graph = _workflow(tmp_path)

    result = CodexGraphRuntime(
        driver=_ResultDriver(pass_result=False),
        run_root=tmp_path / "runs",
    ).run(
        graph=graph,
        selection=selection,
        budget=budget,
        project=detection.descriptor,
        task=task,
    )

    assert result.status == "failed"
    assert result.error_code == "objective_not_met"
