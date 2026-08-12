from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_module():
    path = Path(__file__).parents[1] / "scripts" / "smoke_windows_installer.py"
    specification = importlib.util.spec_from_file_location(
        "empy_windows_installer_smoke",
        path,
    )
    if specification is None or specification.loader is None:
        raise AssertionError(f"Could not load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_rewrites_local_package_inputs_without_touching_other_assignments() -> None:
    module = _load_smoke_module()
    source = (
        "$PackageUrl = 'https://example.test/package.whl'\n"
        "$PackageSha256 = 'old'\n"
        "$Version = '0.1.25'\n"
        "$Target = 'windows-x86_64'"
    )

    updated = module._replace_assignment(
        source,
        "PackageUrl",
        r"file://C:\tmp\package.whl",
    )
    updated = module._replace_assignment(updated, "PackageSha256", "a" * 64)

    assert "$PackageUrl = 'file://C:\\tmp\\package.whl'" in updated
    assert "$PackageSha256 = '" + "a" * 64 + "'" in updated
    assert "$Version = '0.1.25'" in updated
    assert "$Target = 'windows-x86_64'" in updated


def test_rewrite_requires_one_matching_assignment() -> None:
    module = _load_smoke_module()

    try:
        module._replace_assignment("$Version = '0.1.25'", "PackageUrl", "file://x")
    except ValueError as error:
        assert "PackageUrl" in str(error)
    else:
        raise AssertionError("Missing assignment must fail the smoke setup")
