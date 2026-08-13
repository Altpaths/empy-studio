from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from empy_studio.core import DefaultProjectService

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixtures" / "php-site"


def test_php_fixture_is_a_real_independent_project() -> None:
    detection = DefaultProjectService().detect(FIXTURE)

    assert detection.descriptor.project_type == "php"
    assert detection.effective_verification_root == FIXTURE.resolve()
    assert (FIXTURE / "composer.json").is_file()
    assert (FIXTURE / "tests" / "site-audit.php").is_file()


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP is not installed")
def test_php_fixture_audit_passes() -> None:
    result = subprocess.run(
        ["php", "tests/site-audit.php"],
        cwd=FIXTURE,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
