from __future__ import annotations

from pathlib import Path

import pytest

from empy_studio.changelog_validator import (
    validate_changelog,
    validate_release_changelog,
)
from empy_studio.release_version import ReleaseVersion


def write_changelog(
    tmp_path: Path,
    content: str,
) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        content.strip() + "\n",
        encoding="utf-8",
    )
    return path


def test_validates_standard_changelog(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

### Added

- Work in progress

## [1.2.0] - 2026-07-20

### Added

- Release manager

## [1.1.0] - 2026-06-10

### Fixed

- Previous issue
""",
    )

    result = validate_changelog(path)

    assert result.status == "valid"
    assert result.is_valid is True
    assert [
        str(release.version)
        for release in result.releases
    ] == ["1.2.0", "1.1.0"]


def test_rejects_duplicate_versions(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.0.0] - 2026-07-20

### Added

- First

## [1.0.0] - 2026-07-10

### Fixed

- Duplicate
""",
    )

    result = validate_changelog(path)

    assert any(
        issue.code == "duplicate_version"
        for issue in result.issues
    )


def test_rejects_version_order(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.0.0] - 2026-07-20

### Added

- First

## [1.1.0] - 2026-07-10

### Added

- Newer version in wrong place
""",
    )

    result = validate_changelog(path)

    assert any(
        issue.code == "version_order"
        for issue in result.issues
    )


def test_rejects_invalid_date(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.0.0] - 2026-02-31

### Added

- Invalid date
""",
    )

    result = validate_changelog(path)

    assert any(
        issue.code == "invalid_release_date"
        for issue in result.issues
    )


def test_rejects_missing_unreleased(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [1.0.0] - 2026-07-20

### Added

- Release
""",
    )

    result = validate_changelog(path)

    assert any(
        issue.code == "missing_unreleased"
        for issue in result.issues
    )


def test_rejects_release_without_sections(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.0.0] - 2026-07-20

Release text without a subsection.
""",
    )

    result = validate_changelog(path)

    assert any(
        issue.code == "missing_release_sections"
        for issue in result.issues
    )


def test_requires_expected_version_as_latest(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.1.0] - 2026-07-20

### Added

- Latest

## [1.0.0] - 2026-06-20

### Added

- Older
""",
    )

    result = validate_release_changelog(
        path,
        ReleaseVersion.parse("1.0.0"),
    )

    assert any(
        issue.code == "expected_version_not_latest"
        for issue in result.issues
    )


def test_accepts_expected_latest_version(
    tmp_path: Path,
) -> None:
    path = write_changelog(
        tmp_path,
        """
# Changelog

## [Unreleased]

## [1.1.0] - 2026-07-20

### Added

- Latest
""",
    )

    result = validate_release_changelog(
        path,
        ReleaseVersion.parse("1.1.0"),
    )

    assert result.is_valid is True


def test_missing_file_raises(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        validate_changelog(
            tmp_path / "missing.md"
        )
