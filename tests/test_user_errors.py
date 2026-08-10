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
