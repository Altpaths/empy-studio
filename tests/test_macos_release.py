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


def test_macos_release_checksums_use_portable_asset_names() -> None:
    workflows = (
        PROJECT_ROOT / ".github" / "workflows" / "release.yml",
        PROJECT_ROOT / ".github" / "workflows" / "finalize-release.yml",
    )

    for workflow_path in workflows:
        workflow = workflow_path.read_text(encoding="utf-8")
        checksum_lines = tuple(
            line.strip()
            for line in workflow.splitlines()
            if "shasum -a 256" in line
        )
        assert checksum_lines
        assert all("build/" not in line for line in checksum_lines)
        assert all("$SIGNED_ZIP" not in line for line in checksum_lines)
