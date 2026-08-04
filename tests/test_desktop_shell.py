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


def test_desktop_exposes_context_selector_preview() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert hasattr(EmpyDesktopShell, "_build_or_open_context")
    assert hasattr(EmpyDesktopShell, "_render_context_preview")


def test_desktop_exposes_token_budget_panel() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert hasattr(EmpyDesktopShell, "_build_or_open_budget")
    assert hasattr(EmpyDesktopShell, "_render_token_budget")
    assert hasattr(EmpyDesktopShell, "_lock_token_budget")


def test_desktop_exposes_agent_run_graph() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert hasattr(EmpyDesktopShell, "_build_or_open_agent_run_graph")
    assert hasattr(EmpyDesktopShell, "_render_agent_run_graph")
