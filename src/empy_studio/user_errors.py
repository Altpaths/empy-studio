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


def safe_user_error(error: BaseException, *, language: str = "fa") -> str:
    """Convert OS/provider failures to useful messages without leaking host paths."""
    lowered = str(error).casefold()
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
        message = str(error).strip()
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
