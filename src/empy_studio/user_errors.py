from __future__ import annotations

import errno
from pathlib import Path
from typing import Final

_PATH_MARKERS: Final[tuple[str, ...]] = (
    "/",
    "\\",
    "apptranslocation",
    "[errno",
)


def _generic(language: str) -> str:
    return (
        "عملیات انجام نشد. یک پوشهٔ موجود پروژه یا فایل ZIP انتخاب کنید؛ برای بازکردن پروژهٔ قبلی، Empy را با همان workspace قبلی اجرا کنید."
        if language == "fa"
        else "The operation could not be completed. Choose an existing project folder or ZIP; to reopen an earlier project, run Empy with the same workspace."
    )


def _known_actionable_message(message: str, *, language: str) -> str | None:
    """Map common provider/workflow failures to one safe next action.

    The exception text is an implementation diagnostic, not a user interface.
    Keep this mapping deliberately small and specific so an unknown failure is
    still handled by the path-redacting fallback below.
    """

    lowered = message.casefold()
    if any(
        marker in lowered
        for marker in (
            "api key",
            "apikey",
            "dedicated route credential",
            "credential is missing",
            "authentication",
            "unauthorized",
            "not signed in",
            "not authenticated",
            "not logged in",
            "sign in",
            "codex login",
        )
    ):
        return (
            "برای اجرای این اتصال احراز هویت یا کلید لازم است. در مسیر Codex یک‌بار «codex login» را کامل کنید؛ در مسیر OmniRoute متغیر محیطی کلید همان اتصال را تنظیم و سپس وضعیت را Refresh کنید."
            if language == "fa"
            else "This connection needs valid authentication or a key. For the Codex route, complete `codex login`; for OmniRoute, set the route's key environment variable and refresh its status."
        )
    if any(
        marker in lowered
        for marker in (
            "selected free/local model is absent",
            "model_not_found",
            "unknown model",
            "unsupported model",
            "unsupported endpoint",
            "responses is not supported",
        )
    ):
        return (
            "مدل انتخاب‌شده در اتصال فعلی در دسترس نیست؛ فهرست مدل‌های همان مسیر را Refresh کنید و یک مدل صریحِ موجود انتخاب کنید."
            if language == "fa"
            else "The selected model is not available on this connection. Refresh its model list and choose an explicit model that is advertised there."
        )
    if any(
        marker in lowered
        for marker in (
            "local gateway preflight failed",
            "gateway /models check failed",
            "connection refused",
            "failed to connect",
            "no route to host",
        )
    ):
        return (
            "اتصال مدل محلی پاسخ نداد؛ نشانی OmniRoute و روشن‌بودن gateway را بررسی کنید و سپس وضعیت اتصال را Refresh کنید."
            if language == "fa"
            else "The local model gateway did not respond. Check that OmniRoute is running at the configured address, then refresh the connection status."
        )
    if "scope contract missing" in lowered:
        return (
            "دامنهٔ امن این نقش برای هیچ فایل دقیقی ساخته نشد؛ Empy قبل از مصرف توکن اجرای Agent را متوقف کرد تا نقشهٔ پروژه را دوباره بسازد. فایل اصلی تغییر نکرده است."
            if language == "fa"
            else "No bounded exact target was produced for this writing role. Empy stopped before token use so it can rebuild the project scope; the original project was not changed."
        )
    if any(
        marker in lowered
        for marker in (
            "outside this node's ownership",
            "outside this wave's ownership",
            "ownership mismatch",
            "فایل مالکیت‌داده‌شده",
            "فهرست فایل‌های مجاز",
            "محدودهٔ مجاز",
        )
    ):
        return (
            "هدف فایل با ساختار واقعی پروژه منطبق نیست؛ Empy اجرای دوباره را تا اصلاح نقشهٔ پروژه متوقف کرد و فایل اصلی تغییر نکرده است."
            if language == "fa"
            else "The selected file target does not match the project's real layout. Empy paused before another run; the original project was not changed."
        )
    if any(
        marker in lowered
        for marker in (
            "produced no project change",
            "no project change",
            "no project file was changed",
            "no file change",
        )
    ):
        return (
            "Agent تغییر قابل‌تأیید نداد؛ ابتدا بررسی کنید وضعیت درخواستی از قبل وجود دارد یا فایل هدف درست انتخاب نشده است. Verification و ZIP تا نتیجهٔ واقعی متوقف می‌مانند."
            if language == "fa"
            else "The Agent produced no verifiable change. Check whether the requested state already exists or whether the wrong target was selected; Verification and ZIP remain blocked until the result is real."
        )
    if any(
        marker in lowered
        for marker in (
            "codex cli was not found",
            "codex is disabled",
            "lacks required isolated execution capabilities",
            "non-interactive execution",
        )
    ):
        return (
            "Codex برای اجرای واقعی آماده نیست؛ نصب/فعال‌بودن Codex CLI و پشتیبانی از اجرای isolated را بررسی کنید، سپس وضعیت را Refresh کنید."
            if language == "fa"
            else "Codex is not ready for a real run. Check that Codex CLI is installed, enabled and supports isolated non-interactive execution, then refresh its status."
        )
    if any(
        marker in lowered
        for marker in (
            "dependency preparation blocked",
            "dependency bootstrap",
            "composer is not installed",
            "npm is not installed",
            "vendor/autoload.php is missing",
        )
    ):
        return (
            "وابستگی لازم در کپی ایزوله آماده نشد؛ ابزار وابستگی پروژه (Composer یا npm) و lockfile متناظر را بررسی کنید و دوباره اجرا کنید."
            if language == "fa"
            else "A required dependency was not prepared in the isolated copy. Check the project's Composer/npm tool and matching lockfile, then retry."
        )
    if any(
        marker in lowered
        for marker in (
            "fresh-token limit",
            "token budget",
            "token guard",
            "budget_exceeded",
        )
    ):
        return (
            "سقف توکن این مرحله پر شد و نتیجهٔ کامل تولید نشد؛ همان کار را با context کوچک‌تر و بدون discovery تکراری دوباره اجرا کنید."
            if language == "fa"
            else "This step reached Empy's safe token limit before producing a complete result. Retry the same work with compact context and no repeated discovery."
        )
    if "build a plan first" in lowered:
        return (
            "ابتدا تیکت را ثبت و برنامهٔ اجرا را بسازید؛ سپس اجرای Agent را شروع کنید."
            if language == "fa"
            else "Build the ticket plan first, then start the Agent run."
        )
    return None


def safe_user_error(error: BaseException, *, language: str = "fa") -> str:
    """Convert OS/provider failures to useful messages without leaking host paths."""
    message = str(error).strip()
    lowered = message.casefold()
    actionable = _known_actionable_message(message, language=language)
    if actionable is not None:
        return actionable
    if lowered.startswith("verification preflight blocked the provider run:"):
        detail = str(error).split(":", 1)[1].strip()
        # Preflight diagnostics are project-relative by contract.  Keep that
        # actionable detail, but fall back to the generic message if a future
        # diagnostic accidentally includes an absolute host path or URL.
        absolute_markers = (
            "/users/",
            "/private/",
            "/var/",
            "\\users\\",
            "file://",
            "apptranslocation",
        )
        if not detail or any(marker in detail.casefold() for marker in absolute_markers):
            return _generic(language)
        detail = detail[:1200]
        return (
            "پیش از اجرای Agent، Verification جلوی مصرف توکن را گرفت: " + detail
            if language == "fa"
            else "Verification blocked the Agent before token use: " + detail
        )
    if (
        getattr(error, "errno", None) == errno.ERANGE
        or "result too large" in lowered
        or "apptranslocation" in lowered
        or "translocated app" in lowered
    ):
        return (
            "سیستم‌عامل این مسیر موقت/طولانی را نپذیرفت. پروژه را از محل اصلی انتخاب "
            "کنید و Empy Studio را از مسیر عادی اجرا کنید، نه AppTranslocation."
            if language == "fa"
            else "The operating system rejected this temporary or oversized path. Choose the original project location and run Empy Studio from a normal location, not AppTranslocation."
        )
    if isinstance(error, PermissionError) or getattr(error, "errno", None) in {
        errno.EACCES,
        errno.EPERM,
    }:
        return (
            "Empy اجازه‌ی خواندن این مسیر را ندارد. یک پوشه‌ی پروژه‌ی قابل‌دسترسی "
            "انتخاب کنید یا ابتدا پروژه را به یک مسیر کاربری کپی کنید."
            if language == "fa"
            else "Empy cannot read this path. Choose an accessible project folder or copy the project to a user-owned location."
        )
    if isinstance(error, FileNotFoundError):
        return "مسیر انتخاب‌شده دیگر وجود ندارد." if language == "fa" else "The selected path no longer exists."
    if isinstance(error, NotADirectoryError):
        return "یک پوشه‌ی پروژه یا فایل ZIP انتخاب کنید." if language == "fa" else "Choose a project folder or a ZIP file."
    if isinstance(error, IsADirectoryError):
        return "برای این عملیات باید فایل ZIP انتخاب شود." if language == "fa" else "This operation requires a ZIP file."
    if isinstance(error, ValueError):
        if any(
            marker in message.casefold()
            for marker in ("no writable files for writing roles", "no writable files")
        ):
            return (
                "این تیکت به هیچ فایل امن و قابل‌ویرایشی وصل نشد؛ Empy باید فهرست فایل‌های پروژه را دوباره بسازد یا هدف فایل جدید را مشخص کند. فایل اصلی تغییر نکرده است."
                if language == "fa"
                else "This ticket was not assigned a safe writable file. Empy must rebuild the project index or resolve an approved missing target. The original project was not changed."
            )
        known = {
            "Choose an existing project folder or a ZIP archive.": (
                "یک پوشه‌ی موجود پروژه یا فایل ZIP انتخاب کنید."
                if language == "fa"
                else "Choose an existing project folder or a ZIP archive."
            ),
            "project import contains no safe files": (
                "فایل قابل‌استفاده‌ای در پروژه پیدا نشد."
                if language == "fa"
                else "The project contains no usable files."
            ),
            "project archive contains no safe files": (
                "فایل قابل‌استفاده‌ای در ZIP پیدا نشد."
                if language == "fa"
                else "The ZIP contains no usable project files."
            ),
            "project archive exceeds the total size limit": (
                "حجم ZIP از سقف امن Empy بیشتر است."
                if language == "fa"
                else "The ZIP exceeds Empy's safe total size limit."
            ),
            "saved project is no longer available; re-import its folder or ZIP.": (
                "مسیر پروژهٔ ذخیره‌شده دیگر وجود ندارد؛ پوشه یا ZIP پروژه را دوباره وارد کنید."
                if language == "fa"
                else "The saved project path is no longer available; re-import its folder or ZIP."
            ),
            "Empy baseline snapshot is missing; re-import the project.": (
                "نسخهٔ پایهٔ پروژه برای مقایسه پیدا نشد؛ پروژه را دوباره وارد کنید."
                if language == "fa"
                else "The project's baseline snapshot is missing; re-import the project."
            ),
            "A baseline snapshot is required for a change-only ZIP.": (
                "برای ساخت ZIP فقط شامل تغییرات، نسخهٔ پایهٔ پروژه لازم است؛ پروژه را دوباره وارد کنید."
                if language == "fa"
                else "A baseline snapshot is required to create a change-only ZIP; re-import the project."
            ),
            "No changed project files are available for a delta ZIP.": (
                "هیچ فایل تغییرکرده‌ای برای ساخت ZIP وجود ندارد؛ خروجی ناقص ساخته نشد."
                if language == "fa"
                else "There are no changed project files for a delta ZIP; no incomplete archive was created."
            ),
            "The project has deleted file(s); a ZIP extraction cannot delete them automatically. Restore the file or use an explicit deletion step.": (
                "پروژه فایل حذف‌شده دارد؛ استخراج معمولی ZIP نمی‌تواند فایل مقصد را خودکار حذف کند. فایل را برگردانید یا مرحلهٔ حذف صریح اجرا کنید."
                if language == "fa"
                else "The project has deleted files; normal ZIP extraction cannot remove destination files automatically. Restore them or use an explicit deletion step."
            ),
            "The project has deleted file(s); restore them before creating a ZIP.": (
                "پروژه فایل حذف‌شده دارد؛ برای ساخت ZIP ابتدا فایل را برگردانید."
                if language == "fa"
                else "The project has deleted files; restore them before creating a ZIP."
            ),
        }
        if message in known:
            return known[message]
        if any(marker in message.casefold() for marker in _PATH_MARKERS):
            return _generic(language)
        return message or _generic(language)
    message = str(error).strip()
    if any(marker in message.casefold() for marker in _PATH_MARKERS):
        return _generic(language)
    return message or _generic(language)


def safe_path_name(value: str | Path) -> str:
    """Return only a filename for diagnostics that need a stable local label."""
    return Path(value).name or "project"
