from __future__ import annotations

from empy_studio.core.path_policy import is_sensitive_relative_path


def test_runtime_php_config_and_logs_are_sensitive_but_examples_are_not() -> None:
    assert is_sensitive_relative_path("config/config.php")
    assert is_sensitive_relative_path("config/settings.local.php")
    assert is_sensitive_relative_path("storage/logs/app.log")
    assert is_sensitive_relative_path("logs/app.log.1")
    assert not is_sensitive_relative_path("config/config.example.php")
    assert not is_sensitive_relative_path("docs/configuration.md")
