from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from .release_version import ReleaseVersion

_RELEASE_HEADING = re.compile(
    r"^## \[(?P<version>[^\]]+)\]"
    r"(?: - (?P<date>\d{4}-\d{2}-\d{2}))?$"
)

_UNRELEASED_HEADING = "## [Unreleased]"


@dataclass(frozen=True)
class ChangelogIssue:
    code: str
    message: str
    line: int | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChangelogRelease:
    version: ReleaseVersion
    release_date: date
    heading_line: int
    sections: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": str(self.version),
            "release_date": self.release_date.isoformat(),
            "heading_line": self.heading_line,
            "sections": list(self.sections),
        }


@dataclass(frozen=True)
class ChangelogValidationResult:
    status: str
    path: str
    releases: tuple[ChangelogRelease, ...]
    issues: tuple[ChangelogIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "release_count": len(self.releases),
            "issue_count": len(self.issues),
            "releases": [
                release.to_dict()
                for release in self.releases
            ],
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }


def _parse_release_date(
    value: str,
    *,
    line_number: int,
    version: str,
) -> tuple[date | None, ChangelogIssue | None]:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return (
            None,
            ChangelogIssue(
                code="invalid_release_date",
                message=(
                    "Release date must use YYYY-MM-DD format "
                    "and represent a valid calendar date"
                ),
                line=line_number,
                version=version,
            ),
        )

    if parsed > datetime.now(timezone.utc).date():
        return (
            None,
            ChangelogIssue(
                code="future_release_date",
                message="Release date cannot be in the future",
                line=line_number,
                version=version,
            ),
        )

    return parsed, None


def _section_names(
    lines: list[str],
    start_index: int,
    end_index: int,
) -> tuple[str, ...]:
    sections: list[str] = []

    for line in lines[start_index:end_index]:
        if line.startswith("### "):
            name = line[4:].strip()
            if name:
                sections.append(name)

    return tuple(sections)


def validate_changelog(
    changelog_path: str | Path,
    *,
    expected_version: ReleaseVersion | None = None,
    require_unreleased: bool = True,
) -> ChangelogValidationResult:
    path = Path(changelog_path).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    lines = path.read_text(
        encoding="utf-8",
    ).splitlines()

    issues: list[ChangelogIssue] = []
    release_rows: list[
        tuple[int, ReleaseVersion, date]
    ] = []

    unreleased_lines = [
        index + 1
        for index, line in enumerate(lines)
        if line.strip() == _UNRELEASED_HEADING
    ]

    if require_unreleased and not unreleased_lines:
        issues.append(
            ChangelogIssue(
                code="missing_unreleased",
                message=(
                    "CHANGELOG.md must contain "
                    "a single ## [Unreleased] section"
                ),
            )
        )

    if len(unreleased_lines) > 1:
        issues.append(
            ChangelogIssue(
                code="duplicate_unreleased",
                message=(
                    "CHANGELOG.md contains multiple "
                    "## [Unreleased] sections"
                ),
                line=unreleased_lines[1],
            )
        )

    seen_versions: dict[str, int] = {}

    for index, line in enumerate(lines):
        if not line.startswith("## ["):
            continue

        if line.strip() == _UNRELEASED_HEADING:
            continue

        match = _RELEASE_HEADING.fullmatch(
            line.strip()
        )
        line_number = index + 1

        if match is None:
            issues.append(
                ChangelogIssue(
                    code="invalid_release_heading",
                    message=(
                        "Release heading must use "
                        "## [VERSION] - YYYY-MM-DD"
                    ),
                    line=line_number,
                )
            )
            continue

        raw_version = match.group("version")
        raw_date = match.group("date")

        if raw_date is None:
            issues.append(
                ChangelogIssue(
                    code="missing_release_date",
                    message=(
                        "Released versions must include "
                        "a release date"
                    ),
                    line=line_number,
                    version=raw_version,
                )
            )
            continue

        try:
            version = ReleaseVersion.parse(
                raw_version
            )
        except ValueError:
            issues.append(
                ChangelogIssue(
                    code="invalid_release_version",
                    message=(
                        "Release heading contains an invalid "
                        "semantic version"
                    ),
                    line=line_number,
                    version=raw_version,
                )
            )
            continue

        normalized = str(version)

        if normalized in seen_versions:
            issues.append(
                ChangelogIssue(
                    code="duplicate_version",
                    message=(
                        f"Version {normalized} appears "
                        "more than once"
                    ),
                    line=line_number,
                    version=normalized,
                )
            )
            continue

        seen_versions[normalized] = line_number

        release_date, date_issue = _parse_release_date(
            raw_date,
            line_number=line_number,
            version=normalized,
        )
        if date_issue is not None:
            issues.append(date_issue)
            continue

        if release_date is not None:
            release_rows.append(
                (
                    index,
                    version,
                    release_date,
                )
            )

    releases: list[ChangelogRelease] = []

    for position, (
        start_index,
        version,
        release_date,
    ) in enumerate(release_rows):
        end_index = (
            release_rows[position + 1][0]
            if position + 1 < len(release_rows)
            else len(lines)
        )
        sections = _section_names(
            lines,
            start_index + 1,
            end_index,
        )

        if not sections:
            issues.append(
                ChangelogIssue(
                    code="missing_release_sections",
                    message=(
                        "Released versions must contain "
                        "at least one ### section"
                    ),
                    line=start_index + 1,
                    version=str(version),
                )
            )

        releases.append(
            ChangelogRelease(
                version=version,
                release_date=release_date,
                heading_line=start_index + 1,
                sections=sections,
            )
        )

    for earlier, later in pairwise(releases):
        if earlier.version <= later.version:
            issues.append(
                ChangelogIssue(
                    code="version_order",
                    message=(
                        "Released versions must be ordered "
                        "from newest to oldest"
                    ),
                    line=later.heading_line,
                    version=str(later.version),
                )
            )

        if earlier.release_date < later.release_date:
            issues.append(
                ChangelogIssue(
                    code="date_order",
                    message=(
                        "Release dates must be ordered "
                        "from newest to oldest"
                    ),
                    line=later.heading_line,
                    version=str(later.version),
                )
            )

    if expected_version is not None:
        if not releases:
            issues.append(
                ChangelogIssue(
                    code="missing_expected_version",
                    message=(
                        f"Expected release version "
                        f"{expected_version} was not found"
                    ),
                    version=str(expected_version),
                )
            )
        elif releases[0].version != expected_version:
            issues.append(
                ChangelogIssue(
                    code="expected_version_not_latest",
                    message=(
                        f"Latest changelog version must be "
                        f"{expected_version}"
                    ),
                    line=releases[0].heading_line,
                    version=str(expected_version),
                )
            )

    return ChangelogValidationResult(
        status="valid" if not issues else "invalid",
        path=str(path),
        releases=tuple(releases),
        issues=tuple(issues),
    )


def validate_release_changelog(
    changelog_path: str | Path,
    release_version: ReleaseVersion,
) -> ChangelogValidationResult:
    return validate_changelog(
        changelog_path,
        expected_version=release_version,
        require_unreleased=True,
    )
