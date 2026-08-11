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
    assert "run_report" in app_js
    assert "verificationReady" in app_js
    assert 'state.run_status === "completed"' in app_js
    assert 'data-action="choose-zip"' in app_js
    assert 'data-action="refresh-engine"' in app_js
    index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="folder-upload"' in index
    assert 'id="zip-upload"' in index
    assert 'aria-label=' in app_js
    assert "localizeMessage" in app_js
    assert ".report" in (WEB_ROOT / "app.css").read_text(encoding="utf-8")
