from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CodexHostDiagnosticCode = Literal[
    "path_aliases",
    "app_server",
    "state_database",
    "sandbox",
]


@dataclass(frozen=True)
class CodexHostDiagnostic:
    """Safe, provider-output-independent description of a host preflight issue."""

    code: CodexHostDiagnosticCode
    message: str
    remediation: str


_DIAGNOSTICS: tuple[CodexHostDiagnostic, ...] = (
    CodexHostDiagnostic(
        code="path_aliases",
        message=(
            "Codex CLI reported that it could not create its host PATH aliases."
        ),
        remediation=(
            "Allow the Codex CLI host to create its PATH aliases, reinstall or "
            "update Codex CLI, then refresh the environment. Empy will not "
            "disable the sandbox automatically."
        ),
    ),
    CodexHostDiagnostic(
        code="app_server",
        message="Codex could not initialize its local app-server environment.",
        remediation=(
            "Verify host permissions for Codex state directories and use an "
            "approved writable workspace, then refresh the environment."
        ),
    ),
    CodexHostDiagnostic(
        code="state_database",
        message="Codex could not initialize its local state database.",
        remediation=(
            "Verify host permissions for Codex state directories and retry. "
            "Do not grant unrestricted project access as an automatic workaround."
        ),
    ),
    CodexHostDiagnostic(
        code="sandbox",
        message="Codex reported a host sandbox initialization failure.",
        remediation=(
            "Verify host permissions and choose an approved workspace, then "
            "refresh the environment."
        ),
    ),
)

_MARKERS: dict[CodexHostDiagnosticCode, tuple[str, ...]] = {
    "path_aliases": (
        "could not create path aliases",
        "could not create path alias",
    ),
    "app_server": (
        "failed to initialize in-process app-server",
        "in-process app-server client",
        "app-server client",
        "app-server could not initialize",
    ),
    "state_database": (
        "state_5.sqlite",
        "could not open state database",
        "state database could not initialize",
    ),
    "sandbox": (
        "sandbox could not initialize",
        "sandbox initialization failed",
        "could not initialize sandbox",
        "sandbox setup failed",
    ),
}


def detect_codex_host_diagnostic(
    *outputs: str,
) -> CodexHostDiagnostic | None:
    """Detect known host failures without retaining raw provider output."""

    normalized = " ".join(
        " ".join(output.split()).lower()
        for output in outputs
        if output
    )
    if not normalized:
        return None

    for diagnostic in _DIAGNOSTICS:
        if any(marker in normalized for marker in _MARKERS[diagnostic.code]):
            return diagnostic
    return None
