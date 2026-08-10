from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

Severity = Literal[
    "info",
    "low",
    "medium",
    "high",
    "critical",
]

FindingKind = Literal[
    "dependency",
    "secret",
    "source",
    "environment",
]


class AuditRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class SecurityFinding:
    kind: FindingKind
    severity: Severity
    rule_id: str
    message: str
    path: str | None = None
    line: int | None = None

    def validate(self) -> None:
        if not self.rule_id.strip():
            raise ValueError(
                "Security finding rule_id cannot be empty"
            )
        if not self.message.strip():
            raise ValueError(
                "Security finding message cannot be empty"
            )
        if self.line is not None and self.line <= 0:
            raise ValueError(
                "Security finding line must be positive"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DependencyRecord:
    name: str
    specifier: str
    source: str

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Dependency name cannot be empty"
            )
        if not self.source.strip():
            raise ValueError(
                "Dependency source cannot be empty"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditCommand:
    name: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SecurityAuditEvidence:
    schema_version: int
    status: str
    project_root: str
    project_digest: str
    dependencies: tuple[DependencyRecord, ...]
    findings: tuple[SecurityFinding, ...]
    commands: tuple[AuditCommand, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def blocking_findings(
        self,
    ) -> tuple[SecurityFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.severity in {
                "high",
                "critical",
            }
        )

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported security-audit schema"
            )
        if self.status not in {
            "passed",
            "failed",
        }:
            raise ValueError(
                "Unsupported security-audit status"
            )
        if len(self.project_digest) != 64:
            raise ValueError(
                "project_digest must be SHA-256"
            )

        for dependency in self.dependencies:
            dependency.validate()
        for finding in self.findings:
            finding.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "project_root": self.project_root,
            "project_digest": self.project_digest,
            "dependency_count": len(
                self.dependencies
            ),
            "finding_count": len(
                self.findings
            ),
            "blocking_finding_count": len(
                self.blocking_findings
            ),
            "dependencies": [
                item.to_dict()
                for item in self.dependencies
            ],
            "findings": [
                item.to_dict()
                for item in self.findings
            ],
            "commands": [
                item.to_dict()
                for item in self.commands
            ],
        }

    def save(
        self,
        destination: str | Path,
    ) -> Path:
        self.validate()

        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path


@dataclass(frozen=True)
class SecurityAuditConfig:
    project_root: str
    evidence_path: str
    python_executable: str = sys.executable
    source_directory: str = "src"

    def validate(self) -> None:
        root = Path(
            self.project_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise NotADirectoryError(root)
        if not (
            root / "pyproject.toml"
        ).is_file():
            raise ValueError(
                "project_root must contain pyproject.toml"
            )
        if not self.python_executable.strip():
            raise ValueError(
                "python_executable cannot be empty"
            )
        if Path(
            self.source_directory
        ).is_absolute():
            raise ValueError(
                "source_directory must be relative"
            )


_SECRET_RULES: tuple[
    tuple[str, re.Pattern[str], Severity],
    ...,
] = (
    (
        "secret.aws_access_key",
        re.compile(
            r"\bAKIA[0-9A-Z]{16}\b"
        ),
        "critical",
    ),
    (
        "secret.github_token",
        re.compile(
            r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"
        ),
        "critical",
    ),
    (
        "secret.private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?"
            r"PRIVATE KEY-----"
        ),
        "critical",
    ),
    (
        "secret.generic_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password)"
            r"\s*=\s*['\"][^'\"]{12,}['\"]"
        ),
        "high",
    ),
)

_REDACTED_VALUE = "<redacted>"
_URL_CREDENTIALS = re.compile(
    r"(?i)(://[^\s:@]+:)[^@\s]+(@)"
)


def _redact_sensitive_output(value: str) -> str:
    redacted = value
    for _, pattern, _ in _SECRET_RULES:
        redacted = pattern.sub(
            _REDACTED_VALUE,
            redacted,
        )
    return _URL_CREDENTIALS.sub(
        rf"\1{_REDACTED_VALUE}\2",
        redacted,
    )


def redact_sensitive_output(value: str) -> str:
    """Expose the same bounded redaction used by security audit evidence."""

    return _redact_sensitive_output(value)


def _default_runner(
    command: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _project_digest(
    root: Path,
) -> str:
    digest = hashlib.sha256()
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        if any(
            part in ignored
            for part in path.relative_to(root).parts
        ):
            continue

        digest.update(
            path.relative_to(root)
            .as_posix()
            .encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(path.read_bytes())

    return digest.hexdigest()


def _dependency_name(
    requirement: str,
) -> str:
    match = re.match(
        r"\s*([A-Za-z0-9_.-]+)",
        requirement,
    )
    if match is None:
        raise ValueError(
            f"Invalid dependency requirement: {requirement!r}"
        )
    return match.group(1)


def load_declared_dependencies(
    project_root: str | Path,
) -> tuple[DependencyRecord, ...]:
    root = Path(
        project_root
    ).expanduser().resolve()
    data = tomllib.loads(
        (root / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    project = data.get("project", {})
    if not isinstance(project, dict):
        raise TypeError(
            "pyproject project table must be an object"
        )

    records: list[DependencyRecord] = []

    dependencies = project.get(
        "dependencies",
        [],
    )
    if not isinstance(dependencies, list):
        raise TypeError(
            "project.dependencies must be a list"
        )

    for requirement in dependencies:
        value = str(requirement)
        records.append(
            DependencyRecord(
                name=_dependency_name(value),
                specifier=_redact_sensitive_output(value),
                source="project.dependencies",
            )
        )

    optional = project.get(
        "optional-dependencies",
        {},
    )
    if not isinstance(optional, dict):
        raise TypeError(
            "project.optional-dependencies "
            "must be an object"
        )

    for group, requirements in sorted(
        optional.items()
    ):
        if not isinstance(requirements, list):
            raise TypeError(
                "Optional dependency groups "
                "must contain lists"
            )

        for requirement in requirements:
            value = str(requirement)
            records.append(
                DependencyRecord(
                    name=_dependency_name(value),
                    specifier=_redact_sensitive_output(value),
                    source=(
                        "project.optional-dependencies."
                        + str(group)
                    ),
                )
            )

    unique = {
        (
            record.name.lower(),
            record.specifier,
            record.source,
        ): record
        for record in records
    }

    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.name.lower(),
                item.source,
                item.specifier,
            ),
        )
    )


def _scan_secrets(
    root: Path,
) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    allowed_suffixes = {
        ".py",
        ".toml",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".ini",
        ".cfg",
        ".env",
        "",
    }
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        "dist",
        "build",
    }

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        if any(
            part in ignored
            for part in path.relative_to(root).parts
        ):
            continue
        if path.suffix.lower() not in allowed_suffixes:
            continue

        try:
            text = path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            for (
                rule_id,
                pattern,
                severity,
            ) in _SECRET_RULES:
                if pattern.search(line):
                    findings.append(
                        SecurityFinding(
                            kind="secret",
                            severity=severity,
                            rule_id=rule_id,
                            message=(
                                "Potential embedded secret"
                            ),
                            path=path.relative_to(
                                root
                            ).as_posix(),
                            line=line_number,
                        )
                    )

    return findings


class _RiskVisitor(ast.NodeVisitor):
    def __init__(
        self,
        path: str,
    ) -> None:
        self.path = path
        self.findings: list[
            SecurityFinding
        ] = []

    def _add(
        self,
        *,
        severity: Severity,
        rule_id: str,
        message: str,
        node: ast.AST,
    ) -> None:
        self.findings.append(
            SecurityFinding(
                kind="source",
                severity=severity,
                rule_id=rule_id,
                message=message,
                path=self.path,
                line=getattr(
                    node,
                    "lineno",
                    None,
                ),
            )
        )

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:
        function_name = ""

        if isinstance(
            node.func,
            ast.Name,
        ):
            function_name = node.func.id
        elif isinstance(
            node.func,
            ast.Attribute,
        ):
            parts: list[str] = []
            current: ast.expr = node.func
            while isinstance(
                current,
                ast.Attribute,
            ):
                parts.append(current.attr)
                current = current.value
            if isinstance(
                current,
                ast.Name,
            ):
                parts.append(current.id)
            function_name = ".".join(
                reversed(parts)
            )

        if function_name in {
            "eval",
            "exec",
        }:
            self._add(
                severity="high",
                rule_id=(
                    "source.dynamic_execution"
                ),
                message=(
                    f"Use of {function_name}()"
                ),
                node=node,
            )

        if function_name in {
            "pickle.load",
            "pickle.loads",
        }:
            self._add(
                severity="high",
                rule_id=(
                    "source.unsafe_deserialization"
                ),
                message=(
                    "Potential unsafe pickle "
                    "deserialization"
                ),
                node=node,
            )

        if function_name in {
            "subprocess.run",
            "subprocess.call",
            "subprocess.Popen",
            "subprocess.check_call",
            "subprocess.check_output",
        }:
            shell_true = any(
                keyword.arg == "shell"
                and isinstance(
                    keyword.value,
                    ast.Constant,
                )
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if shell_true:
                self._add(
                    severity="high",
                    rule_id=(
                        "source.subprocess_shell_true"
                    ),
                    message=(
                        "subprocess call uses shell=True"
                    ),
                    node=node,
                )

        self.generic_visit(node)


def _scan_python_source(
    source_root: Path,
    project_root: Path,
) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    if not source_root.exists():
        return [
            SecurityFinding(
                kind="source",
                severity="medium",
                rule_id="source.directory_missing",
                message=(
                    "Configured source directory "
                    "does not exist"
                ),
                path=source_root.relative_to(
                    project_root
                ).as_posix(),
            )
        ]

    for path in sorted(
        source_root.rglob("*.py")
    ):
        if path.is_symlink():
            continue
        try:
            tree = ast.parse(
                path.read_text(
                    encoding="utf-8"
                ),
                filename=str(path),
            )
        except SyntaxError as exc:
            findings.append(
                SecurityFinding(
                    kind="source",
                    severity="high",
                    rule_id=(
                        "source.syntax_error"
                    ),
                    message=str(exc),
                    path=path.relative_to(
                        project_root
                    ).as_posix(),
                    line=exc.lineno,
                )
            )
            continue

        visitor = _RiskVisitor(
            path.relative_to(
                project_root
            ).as_posix()
        )
        visitor.visit(tree)
        findings.extend(
            visitor.findings
        )

    return findings


def run_security_audit(
    config: SecurityAuditConfig,
    *,
    runner: AuditRunner | None = None,
) -> SecurityAuditEvidence:
    config.validate()

    execute = runner or _default_runner
    root = Path(
        config.project_root
    ).expanduser().resolve()
    source_candidate = root / config.source_directory
    relative_source = source_candidate.relative_to(root)
    current = root
    for part in relative_source.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                "source_directory cannot contain symlinks"
            )
    source_root = source_candidate.resolve()

    if (
        root not in source_root.parents
        and source_root != root
    ):
        raise ValueError(
            "source_directory escapes project root"
        )

    dependencies = load_declared_dependencies(
        root
    )
    findings = [
        *_scan_secrets(root),
        *_scan_python_source(
            source_root,
            root,
        ),
    ]

    commands: list[AuditCommand] = []

    for name, command in (
        (
            "pip_check",
            [
                config.python_executable,
                "-m",
                "pip",
                "check",
            ],
        ),
        (
            "pip_inventory",
            [
                config.python_executable,
                "-m",
                "pip",
                "list",
                "--format=json",
            ],
        ),
    ):
        result = execute(
            command,
            cwd=root,
        )
        commands.append(
            AuditCommand(
                name=name,
                command=tuple(command),
                returncode=result.returncode,
                stdout=_redact_sensitive_output(
                    result.stdout
                ),
                stderr=_redact_sensitive_output(
                    result.stderr
                ),
            )
        )

        if (
            name == "pip_check"
            and result.returncode != 0
        ):
            findings.append(
                SecurityFinding(
                    kind="dependency",
                    severity="high",
                    rule_id=(
                        "dependency.pip_check_failed"
                    ),
                    message=(
                        _redact_sensitive_output(
                            result.stderr.strip()
                        )
                        or _redact_sensitive_output(
                            result.stdout.strip()
                        )
                        or "pip check failed"
                    ),
                )
            )

        if (
            name == "pip_inventory"
            and result.returncode != 0
        ):
            findings.append(
                SecurityFinding(
                    kind="environment",
                    severity="medium",
                    rule_id=(
                        "environment.inventory_failed"
                    ),
                    message=(
                        "Unable to collect installed "
                        "package inventory"
                    ),
                )
            )

    blocking = [
        finding
        for finding in findings
        if finding.severity in {
            "high",
            "critical",
        }
    ]

    command_failures = [
        command
        for command in commands
        if (
            command.name == "pip_check"
            and not command.passed
        )
    ]

    evidence = SecurityAuditEvidence(
        schema_version=1,
        status=(
            "passed"
            if not blocking
            and not command_failures
            else "failed"
        ),
        project_root=str(root),
        project_digest=_project_digest(
            root
        ),
        dependencies=dependencies,
        findings=tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.severity,
                    item.rule_id,
                    item.path or "",
                    item.line or 0,
                ),
            )
        ),
        commands=tuple(commands),
    )
    evidence.save(
        config.evidence_path
    )
    return evidence


def require_security_audit(
    evidence: SecurityAuditEvidence,
) -> None:
    evidence.validate()

    if evidence.passed:
        return

    blockers = [
        finding.rule_id
        for finding in evidence.blocking_findings
    ]

    raise RuntimeError(
        "Security audit failed: "
        + ", ".join(blockers)
    )
