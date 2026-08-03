from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Literal

VersionBump = Literal["major", "minor", "patch"]

_VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>"
    r"(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*"
    r"))?"
    r"(?:\+(?P<build>"
    r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*"
    r"))?$"
)


@total_ordering
@dataclass(frozen=True)
class ReleaseVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> ReleaseVersion:
        match = _VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ValueError(
                f"Invalid semantic version: {value!r}"
            )

        prerelease = match.group("prerelease")
        build = match.group("build")

        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=(
                tuple(prerelease.split("."))
                if prerelease
                else ()
            ),
            build=(
                tuple(build.split("."))
                if build
                else ()
            ),
        )

    def __post_init__(self) -> None:
        if min(self.major, self.minor, self.patch) < 0:
            raise ValueError(
                "Semantic version components cannot be negative"
            )

        for identifier in self.prerelease:
            if not identifier:
                raise ValueError(
                    "Prerelease identifiers cannot be empty"
                )
            if not re.fullmatch(
                r"[0-9A-Za-z-]+",
                identifier,
            ):
                raise ValueError(
                    f"Invalid prerelease identifier: "
                    f"{identifier!r}"
                )
            if (
                identifier.isdigit()
                and len(identifier) > 1
                and identifier.startswith("0")
            ):
                raise ValueError(
                    "Numeric prerelease identifiers cannot "
                    "contain leading zeroes"
                )

        for identifier in self.build:
            if not identifier or not re.fullmatch(
                r"[0-9A-Za-z-]+",
                identifier,
            ):
                raise ValueError(
                    f"Invalid build identifier: {identifier!r}"
                )

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    @property
    def core(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def bump(self, level: VersionBump) -> ReleaseVersion:
        if level == "major":
            return ReleaseVersion(self.major + 1, 0, 0)
        if level == "minor":
            return ReleaseVersion(
                self.major,
                self.minor + 1,
                0,
            )
        if level == "patch":
            return ReleaseVersion(
                self.major,
                self.minor,
                self.patch + 1,
            )
        raise ValueError(
            f"Unsupported version bump: {level!r}"
        )

    def with_prerelease(
        self,
        *identifiers: str,
    ) -> ReleaseVersion:
        if not identifiers:
            raise ValueError(
                "At least one prerelease identifier is required"
            )
        return ReleaseVersion(
            self.major,
            self.minor,
            self.patch,
            prerelease=tuple(identifiers),
        )

    def without_metadata(self) -> ReleaseVersion:
        return ReleaseVersion(
            self.major,
            self.minor,
            self.patch,
            prerelease=self.prerelease,
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ReleaseVersion):
            return NotImplemented

        if self.core != other.core:
            return self.core < other.core

        if self.prerelease == other.prerelease:
            return False

        if not self.prerelease:
            return False
        if not other.prerelease:
            return True

        for left, right in zip(
            self.prerelease,
            other.prerelease,
        ):
            if left == right:
                continue

            left_numeric = left.isdigit()
            right_numeric = right.isdigit()

            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric:
                return True
            if right_numeric:
                return False
            return left < right

        return len(self.prerelease) < len(
            other.prerelease
        )
