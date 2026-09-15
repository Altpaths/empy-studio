from __future__ import annotations

import errno

from empy_studio.user_errors import safe_user_error


def test_permission_error_does_not_leak_the_host_path() -> None:
    error = PermissionError(errno.EACCES, "Permission denied", "/private/secret/project")

    message = safe_user_error(error)

    assert "Permission denied" not in message
    assert "/private/secret/project" not in message
    assert "اجازه" in message


def test_translocated_path_has_actionable_bilingual_message() -> None:
    error = OSError(errno.ERANGE, "Result too large", "/AppTranslocation/temporary")

    assert "AppTranslocation" in safe_user_error(error)
    english = safe_user_error(error, language="en")
    assert "AppTranslocation" in english
    assert "/AppTranslocation/temporary" not in english


def test_missing_saved_project_has_a_reimport_action() -> None:
    error = ValueError(
        "saved project is no longer available; re-import its folder or ZIP."
    )

    assert "دوباره وارد" in safe_user_error(error)
    assert "re-import" in safe_user_error(error, language="en")


def test_unowned_writer_failure_has_a_safe_bilingual_message() -> None:
    error = ValueError(
        "approved implementation plan has no writable files for writing roles (backend)"
    )

    fa = safe_user_error(error)
    en = safe_user_error(error, language="en")

    assert "فایل" in fa
    assert "تغییر نکرده" in fa
    assert "writable file" in en
    assert "original project was not changed" in en


def test_preflight_failure_preserves_relative_diagnostic_without_host_path() -> None:
    error = RuntimeError(
        "Verification preflight blocked the provider run: "
        "Static web validation failed: public_html/assets/site.css: "
        "local css target 'assets/missing.png' was not found"
    )

    fa = safe_user_error(error)
    en = safe_user_error(error, language="en")

    assert "public_html/assets/site.css" in fa
    assert "assets/missing.png" in en
    assert "Verification" in en


def test_preflight_failure_with_absolute_path_falls_back_to_safe_message() -> None:
    error = RuntimeError(
        "Verification preflight blocked the provider run: "
        "/Users/example/project/public_html/index.html is invalid"
    )

    message = safe_user_error(error, language="en")

    assert "/Users/example/project" not in message
    assert "Choose an existing project folder" in message
