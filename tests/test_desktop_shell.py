from __future__ import annotations

from empy_studio.desktop.shell import NAVIGATION


def test_desktop_navigation_contract() -> None:
    assert tuple(item.key for item in NAVIGATION) == (
        "home",
        "projects",
        "runs",
        "sync",
        "verification",
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


def test_desktop_exposes_codex_execution_runtime() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert hasattr(EmpyDesktopShell, "_start_codex_run")
    assert hasattr(EmpyDesktopShell, "_render_codex_run")
    assert hasattr(EmpyDesktopShell, "_cancel_codex_run")
    assert hasattr(EmpyDesktopShell, "_render_runs")


def test_desktop_exposes_driver_settings_and_capability_matrix() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert hasattr(EmpyDesktopShell, "_render_driver_settings")
    assert hasattr(EmpyDesktopShell, "_save_driver_settings")
    assert hasattr(EmpyDesktopShell, "_refresh_driver_settings")
    assert hasattr(EmpyDesktopShell, "_selected_driver_inspection")


def test_desktop_exposes_sync_conflict_ui() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert "sync" in tuple(item.key for item in NAVIGATION)
    assert hasattr(EmpyDesktopShell, "_render_sync_reports")
    assert hasattr(EmpyDesktopShell, "_render_sync_detail")
    assert hasattr(EmpyDesktopShell, "_resolve_selected_conflict")
    assert hasattr(EmpyDesktopShell, "_apply_current_sync")


def test_desktop_exposes_verification_pipeline_ui() -> None:
    from empy_studio.desktop.shell import EmpyDesktopShell

    assert "verification" in tuple(item.key for item in NAVIGATION)
    assert hasattr(EmpyDesktopShell, "_render_verification")
    assert hasattr(EmpyDesktopShell, "_start_verification")
    assert hasattr(EmpyDesktopShell, "_finalize_verification")
