from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from empy_studio.core import (
    ContextPolicy,
    DefaultProjectService,
    ProductTask,
    ProjectDetection,
    approve_execution_plan,
    build_context_selection,
    generate_execution_plan,
)
from empy_studio.core.context_selector import _task_requests_data_model_changes
from empy_studio.core.planner import (
    classify_intent,
    requests_implementation,
)


def _php_project(root: Path) -> ProjectDetection:
    (root / "public_html").mkdir()
    public_html = root / "public_html"
    (public_html / "composer.json").write_text(
        '{"name":"intent/site"}\n',
        encoding="utf-8",
    )
    (public_html / "index.php").write_text(
        "<?php echo 'home';\n",
        encoding="utf-8",
    )
    (public_html / "tests").mkdir()
    return DefaultProjectService().detect(root)


def _task(root: Path, text: str, *, kind: str = "custom") -> ProductTask:
    return ProductTask(
        task_id="intent-matrix",
        project_root=str(root.resolve()),
        kind=kind,  # type: ignore[arg-type]
        title=text,
        objective=text,
        requirements=(text,),
        constraints=("Do not change unrelated files",),
        definition_of_done=("The requested behavior is verified",),
        status="ready_for_planning",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("Add contact form", {"frontend"}),
        ("Add contact form with email delivery", {"frontend", "backend"}),
        ("Add navigation menu", {"frontend"}),
        ("Build dashboard", {"frontend"}),
        ("Add data table", {"frontend"}),
        ("Create database table", {"backend"}),
        ("Add chart", {"frontend"}),
        ("Add realtime chart from API", {"frontend", "backend"}),
        ("Make responsive on mobile", {"frontend"}),
        ("Improve accessibility/WCAG", {"frontend"}),
        ("Add SEO metadata", {"frontend"}),
        ("Generate dynamic sitemap route", {"frontend", "backend"}),
        ("Add login", {"frontend", "backend", "security"}),
        ("Add payment checkout", {"frontend", "backend", "security"}),
        ("Update assets and images", {"frontend"}),
        ("Upload images to storage", {"frontend", "backend"}),
        ("Add upload button", {"frontend"}),
        ("Add save button", {"frontend"}),
        ("Change header/footer/content", {"frontend"}),
        ("Improve homepage", {"frontend"}),
        ("Add search", {"frontend"}),
        ("Add search with database results", {"frontend", "backend"}),
        ("Add filters and pagination", {"frontend"}),
        ("Add email notifications", {"frontend", "backend"}),
        ("Add user roles", {"frontend", "backend", "security"}),
        ("Add admin panel", {"frontend", "backend"}),
        ("Add subscription billing", {"frontend", "backend"}),
        ("Add websocket chat", {"frontend", "backend"}),
        ("Add captcha", {"frontend", "backend", "security"}),
        ("Add CORS", {"backend", "security"}),
        ("Add audit log", {"backend", "security"}),
        ("Add dark mode", {"frontend"}),
        ("Add service worker", {"frontend"}),
        ("Add PWA offline support", {"frontend"}),
        ("Add export CSV", {"frontend", "backend"}),
        ("Add PDF report", {"frontend", "backend"}),
        ("Add file download", {"frontend", "backend"}),
        ("Add multilingual support", {"frontend"}),
        ("Fix broken links", {"frontend"}),
        ("Create users table", {"backend"}),
        ("فرم تماس اضافه کن", {"frontend"}),
        ("منوی ناوبری اضافه کن", {"frontend"}),
        ("داشبورد بساز", {"frontend"}),
        ("جدول نمایش بده", {"frontend"}),
        ("نمودار اضافه کن", {"frontend"}),
        ("دسترسی‌پذیری را اصلاح کن", {"frontend"}),
        ("سئو و متادیتا اضافه کن", {"frontend"}),
        ("ورود و ثبت‌نام را اضافه کن", {"frontend", "backend", "security"}),
        ("واکنش‌گرا کن", {"frontend"}),
        ("پشتیبانی چندزبانه", {"frontend"}),
        ("چت بلادرنگ اضافه کن", {"frontend", "backend"}),
        ("محدودیت درخواست اضافه کن", {"backend", "security"}),
        ("گزارش‌گیری از پرداخت‌ها", {"frontend", "backend", "security"}),
        ("Update FinanceService.php", {"backend"}),
        ("Update index.php", {"frontend"}),
        ("Change App.tsx", {"frontend"}),
        ("Change src/components/Button.ts", {"frontend"}),
    ),
)
def test_bilingual_design_input_matrix_is_domain_complete(
    text: str,
    expected: set[str],
) -> None:
    profile = classify_intent(text)

    assert set(profile.domains) == expected
    assert profile.frontend == ("frontend" in expected)
    assert profile.backend == ("backend" in expected)
    assert profile.security == ("security" in expected)
    assert profile.implementation


def test_accessibility_never_creates_security_domain() -> None:
    for text in (
        "Improve accessibility",
        "Fix WCAG and keyboard navigation",
        "دسترسی‌پذیری را اصلاح کن",
        "استاندارد دسترسی پذیری را بهتر کن",
    ):
        profile = classify_intent(text)
        assert profile.frontend
        assert not profile.security


def test_table_ui_is_not_database_ownership() -> None:
    assert not _task_requests_data_model_changes("Add a data table to the dashboard")
    assert not _task_requests_data_model_changes("جدول نمایش بده")
    assert _task_requests_data_model_changes("Create a database table")
    assert _task_requests_data_model_changes("Create users table")
    assert _task_requests_data_model_changes("Store price history")


def test_display_records_and_save_button_stay_presentation_only() -> None:
    assert set(classify_intent("Add table to show records").domains) == {"frontend"}
    assert set(classify_intent("Display records").domains) == {"frontend"}
    assert set(classify_intent("نمایش سوابق").domains) == {"frontend"}
    assert set(classify_intent("Add save button").domains) == {"frontend"}


def test_browser_storage_stays_frontend_until_server_storage_is_explicit() -> None:
    assert set(classify_intent("Save preferences to local storage").domains) == {"frontend"}
    assert set(classify_intent("فرم را در ذخیره سازی محلی نگه دار").domains) == {"frontend"}
    assert set(classify_intent("Save form preferences through the storage API").domains) == {
        "frontend",
        "backend",
    }


def test_read_only_domain_nouns_do_not_claim_implementation() -> None:
    assert not requests_implementation("Audit accessibility and review the chart")
    assert not requests_implementation("بررسی دسترسی‌پذیری و نمودار")
    assert requests_implementation("Improve accessibility and update the chart")


def test_persian_selectable_chart_imperative_skips_redundant_discovery(
    tmp_path: Path,
) -> None:
    """A trailing Persian ``کن`` must still route a real implementation.

    This is the exact shape that previously created a provider Discovery node
    before the frontend/backend writers.  The local Project Brain already
    supplies the bounded scope, so the approved graph must start at the
    implementation specialists.
    """

    project = _php_project(tmp_path)
    text = "نمودار بخش ارزیابی دارایی را قابل انتخاب برای هر دارایی کن نه اینکه برای هر دارایی یکی"
    task = _task(tmp_path, text)

    assert requests_implementation(text)
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )

    assert [step.suggested_agent for step in plan.steps] == [
        "frontend",
        "backend",
    ]
    assert all(step.step_id != "discovery" for step in plan.steps)


def test_recovery_context_never_reintroduces_provider_discovery(
    tmp_path: Path,
) -> None:
    project = _php_project(tmp_path)
    text = "نمودار بخش ارزیابی دارایی را قابل انتخاب کن"
    task = _task(
        tmp_path,
        text,
    )
    task = replace(
        task,
        constraints=(
            *task.constraints,
            "Recovery owner: frontend. Fix only the confirmed failure.",
            "Previous Empy execution failed and the next attempt must resolve its confirmed root cause before release:",
        ),
    )

    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )

    assert all(step.suggested_agent != "discovery" for step in plan.steps)


@pytest.mark.parametrize(
    ("text", "role", "expected_path"),
    (
        ("Update FinanceService.php", "backend", "public_html/FinanceService.php"),
        ("Update index.php", "frontend", "public_html/index.php"),
        ("Change App.tsx", "frontend", "public_html/App.tsx"),
    ),
)
def test_unqualified_named_files_are_exact_context_targets(
    tmp_path: Path,
    text: str,
    role: str,
    expected_path: str,
) -> None:
    project = _php_project(tmp_path)
    target = tmp_path / expected_path
    target.write_text("<?php echo 'target';\n" if target.suffix == ".php" else "export default {};\n", encoding="utf-8")
    task = _task(tmp_path, text)
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(
        task=task,
        project=project,
        plan=plan,
        policy=ContextPolicy(
            max_files_per_pack=3,
            max_bytes_per_file=1024,
            max_total_bytes_per_pack=4096,
            max_candidate_file_bytes=8192,
            max_candidates=100,
        ),
    )
    pack = next(pack for pack in selection.packs if pack.agent_role == role)
    assert expected_path in {item.relative_path for item in pack.files}
    assert any("explicitly named in ticket" in item.reasons for item in pack.files if item.relative_path == expected_path)


def test_named_file_token_tolerates_sentence_punctuation() -> None:
    assert classify_intent("Update FinanceService.php.").explicit_files == ("FinanceService.php",)


def test_missing_laravel_homepage_uses_framework_target(tmp_path: Path) -> None:
    (tmp_path / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
    (tmp_path / "composer.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "resources" / "views").mkdir(parents=True)
    project = DefaultProjectService().detect(tmp_path)
    task = _task(tmp_path, "Build the homepage")
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    frontend = next(pack for pack in selection.packs if pack.agent_role == "frontend")
    assert "resources/views/index.blade.php" in {item.relative_path for item in frontend.files}
    assert any(
        item.relative_path == "resources/views/index.blade.php"
        and item.content == ""
        for item in frontend.files
    )


def test_missing_named_react_file_uses_exact_source_target(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"intent/react-site"}\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    project = DefaultProjectService().detect(tmp_path)
    task = _task(tmp_path, "Change App.tsx")
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    frontend = next(pack for pack in selection.packs if pack.agent_role == "frontend")
    target = next(item for item in frontend.files if item.relative_path == "src/App.tsx")
    assert target.content == ""
    assert "approved frontend target is currently missing" in target.reasons


def test_missing_named_seo_file_uses_exact_public_target(tmp_path: Path) -> None:
    public_html = tmp_path / "public_html"
    public_html.mkdir()
    (public_html / "composer.json").write_text("{}\n", encoding="utf-8")
    project = DefaultProjectService().detect(tmp_path)
    task = _task(tmp_path, "Add sitemap.xml")
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    frontend = next(pack for pack in selection.packs if pack.agent_role == "frontend")
    target = next(item for item in frontend.files if item.relative_path == "public_html/sitemap.xml")
    assert target.content == ""
    assert "approved frontend target is currently missing" in target.reasons


def test_verification_relative_named_path_resolves_inside_nested_root(tmp_path: Path) -> None:
    public_html = tmp_path / "public_html"
    (public_html / "src").mkdir(parents=True)
    (public_html / "composer.json").write_text("{}\n", encoding="utf-8")
    (public_html / "index.php").write_text("<?php echo 'home';\n", encoding="utf-8")
    (public_html / "src" / "App.tsx").write_text("export default {}\n", encoding="utf-8")
    project = DefaultProjectService().detect(tmp_path)
    task = _task(tmp_path, "Change src/App.tsx")
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    frontend = next(pack for pack in selection.packs if pack.agent_role == "frontend")
    target = next(item for item in frontend.files if item.relative_path == "public_html/src/App.tsx")
    assert target.content == "export default {}\n"
    assert "explicitly named in ticket" in target.reasons


def test_unqualified_existing_backend_file_resolves_below_source_root(tmp_path: Path) -> None:
    public_html = tmp_path / "public_html"
    (public_html / "src").mkdir(parents=True)
    (public_html / "composer.json").write_text("{}\n", encoding="utf-8")
    (public_html / "src" / "FinanceService.php").write_text(
        "<?php class FinanceService {}\n",
        encoding="utf-8",
    )
    project = DefaultProjectService().detect(tmp_path)
    task = _task(tmp_path, "Update FinanceService.php")
    plan = approve_execution_plan(
        generate_execution_plan(task=task, project=project),
        current_task=task,
    )
    selection = build_context_selection(task=task, project=project, plan=plan)
    backend = next(pack for pack in selection.packs if pack.agent_role == "backend")
    assert "public_html/src/FinanceService.php" in {
        item.relative_path for item in backend.files
    }
