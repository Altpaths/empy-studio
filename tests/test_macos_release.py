from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_builds_the_documented_clean_macos_trial() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "--clean-workspace" in workflow
    build_start = workflow.index("python scripts/build_macos_app.py")
    build_end = workflow.index("test -x", build_start)
    assert "--clean-workspace" in workflow[build_start:build_end]


def test_clean_macos_entrypoint_forces_a_new_workspace() -> None:
    entrypoint = (PROJECT_ROOT / "scripts" / "macos_clean_app_entrypoint.py").read_text(
        encoding="utf-8"
    )

    assert 'arguments = ["--clean", *arguments]' in entrypoint
