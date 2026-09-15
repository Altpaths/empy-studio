from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.core.path_policy import (
    is_agent_denied_relative_path,
    is_delivery_excluded_relative_path,
    is_generated_relative_path,
    is_sensitive_relative_path,
    normalize_relative_path,
    project_path,
    scope_contains,
    scopes_overlap,
)


def test_runtime_php_config_and_logs_are_sensitive_but_examples_are_not() -> None:
    assert is_sensitive_relative_path("config/config.php")
    assert is_sensitive_relative_path("config/settings.local.php")
    assert is_sensitive_relative_path("storage/logs/app.log")
    assert is_sensitive_relative_path("logs/app.log.1")
    assert not is_sensitive_relative_path("config/config.example.php")
    assert not is_sensitive_relative_path("docs/configuration.md")


@pytest.mark.parametrize(
    "value",
    ("", ".", "../escape", "src/../../escape", "/tmp/escape", "C:/escape", "src\\..\\escape"),
)
def test_relative_path_policy_rejects_root_traversal_and_absolute_paths(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_relative_path(value)


def test_directory_scopes_are_segment_aware_and_never_mean_project_root() -> None:
    assert scope_contains("src/", "src/components/Button.tsx")
    assert not scope_contains("src/", "src-old/components/Button.tsx")
    assert not scope_contains("src/", "src")
    assert not scope_contains(".", "src/main.ts")
    assert scopes_overlap("src/", "src/components/")
    assert scopes_overlap("src/components/Button.tsx", "src/")
    assert not scopes_overlap("src/", "public/")


def test_generated_and_delivery_exclusions_share_the_same_deny_policy() -> None:
    for path in (
        "node_modules/pkg/index.js",
        "src/widget.js.map",
        "dist/app.min.js",
        "package-lock.json",
    ):
        assert is_generated_relative_path(path)
        assert is_agent_denied_relative_path(path)
    for path in ("dist/app.min.js", "package-lock.json"):
        assert is_delivery_excluded_relative_path(path)
    for path in (".env.local", "certificate.pem"):
        assert not is_generated_relative_path(path)
        assert is_delivery_excluded_relative_path(path)
        assert is_agent_denied_relative_path(path)


def test_project_path_rejects_symlink_components_and_missing_exact_targets(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        project_path(root, "link/secret.txt", allow_directory=False)
    target = project_path(root, "src/new.ts", allow_directory=False)
    assert target == root / "src/new.ts"


def test_project_path_rejects_a_file_disguised_as_directory_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "file.ts").write_text("export {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="directory scope"):
        project_path(root, "src/file.ts/", allow_directory=True)


def test_policy_predicates_fail_closed_for_unsafe_paths() -> None:
    assert is_generated_relative_path("../escape")
    assert is_delivery_excluded_relative_path("../escape")
    assert is_agent_denied_relative_path("../escape")
