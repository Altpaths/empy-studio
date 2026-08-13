from __future__ import annotations

from pathlib import Path

from empy_studio.web_desktop import _content_type_for_asset

WEB_ROOT = Path(__file__).parents[1] / "src" / "empy_studio" / "web"


def test_web_asset_mime_types_cover_logo_and_scripts() -> None:
    assert _content_type_for_asset(Path("empy-logo.png")) == "image/png"
    assert _content_type_for_asset(Path("app.js")) == "text/javascript"
    assert _content_type_for_asset(Path("app.css")) == "text/css"


def test_brand_asset_and_event_delegation_are_wired() -> None:
    assert (WEB_ROOT / "empy-logo.png").is_file()
    assert "/assets/empy-logo.png" in (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert 'data-action="' in app_js
    assert "onclick=" not in app_js
    assert "window.importPath" not in app_js
    assert "renderRunReport" in app_js
    assert "renderGuidance" in app_js
    assert "renderImportReport" in app_js
    assert "enhanceImportUi" in app_js
    assert "import_report" in app_js
    assert "enhanceReportUi" in app_js
    assert "technicalDetails" in app_js
    assert "run_report" in app_js
    assert "state.release_gate || report.export" in app_js
    assert "exportVerified" in app_js
    assert "deltaDownloadHint" in app_js
    assert "localizeMessage(item)" in app_js
    assert 'class="secondary download-link"' in app_js
    assert "verificationReady" in app_js
    assert 'state.run_status === "completed"' in app_js
    assert 'data-action="choose-zip"' in app_js
    assert "startHere" in app_js
    assert "projectStartHint" in app_js
    assert "chooseProject" in app_js
    assert "ذخیره نشده است" in app_js
    assert "start-card" in app_js
    assert "project-card" in app_js
    render_project = app_js.split("function renderProject()", 1)[1].split("function renderImportReport", 1)[0]
    assert 'class="start-hint"' in render_project
    assert "start-description" in render_project
    assert 'id="path"' in render_project
    assert 'data-action="choose-folder"' in render_project
    assert 'data-action="choose-zip"' in render_project
    assert "renderEngine(engine)" in render_project
    assert "import-path" not in render_project
    assert 'target?.id !== "path"' in app_js
    assert "projectUnavailable" in app_js
    assert 'data-action="refresh-engine"' in app_js
    assert "let taskDraft = \"\"" in app_js
    assert 'addEventListener("input"' in app_js
    assert "taskDraftProjectId" in app_js
    assert "const field = document.querySelector(\"#tasks\")" in app_js
    index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="folder-upload"' in index
    assert 'id="zip-upload"' in index
    assert 'aria-label=' in app_js
    assert "localizeMessage" in app_js
    app_css = (WEB_ROOT / "app.css").read_text(encoding="utf-8")
    assert ".report" in app_css
    assert ".action-guide" in app_css
    assert ".technical-details" in app_css
    assert ".import-report" in app_css
    assert ".message.warning" in app_css
    assert ".download-link{display:inline-block;text-decoration:none;font:inherit" in app_css
