from __future__ import annotations

from empy_studio.desktop.shell import NAVIGATION


def test_desktop_navigation_contract() -> None:
    assert tuple(item.key for item in NAVIGATION) == (
        "home",
        "projects",
        "runs",
        "settings",
    )


def test_desktop_navigation_content_is_non_empty() -> None:
    assert all(item.label.strip() for item in NAVIGATION)
    assert all(item.description.strip() for item in NAVIGATION)
