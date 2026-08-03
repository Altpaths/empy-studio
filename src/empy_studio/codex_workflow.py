from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

CodexExecutionMode = Literal[
    "non_interactive",
    "interactive",
    "manual",
]
CodexSandbox = Literal[
    "read-only",
    "workspace-write",
    "danger-full-access",
]
CodexApprovalPolicy = Literal[
    "untrusted",
    "on-request",
    "never",
]
CodexRunStatus = Literal[
    "planned",
    "prepared",
    "running",
    "completed",
    "failed",
    "manual_required",
]


@dataclass(frozen=True)
class CodexTaskContract:
    task_id: str
    title: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> CodexTaskContract:
        contract = cls(
            task_id=str(data["task_id"]),
            title=str(data["title"]),
            objective=str(data["objective"]),
            acceptance_criteria=tuple(
                str(item)
                for item in data.get("acceptance_criteria", [])
            ),
            allowed_paths=tuple(
                str(item)
                for item in data.get("allowed_paths", [])
            ),
            forbidden_paths=tuple(
                str(item)
                for item in data.get("forbidden_paths", [])
            ),
            verification_commands=tuple(
                str(item)
                for item in data.get(
                    "verification_commands",
                    [],
                )
            ),
            constraints=tuple(
                str(item)
                for item in data.get("constraints", [])
            ),
        )
        contract.validate()
        return contract

    def validate(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")
        if not self.acceptance_criteria:
            raise ValueError(
                "At least one acceptance criterion is required"
            )

        overlap = sorted(
            set(self.allowed_paths).intersection(
                self.forbidden_paths
            )
        )
        if overlap:
            raise ValueError(
                f"Paths cannot be both allowed and forbidden: "
                f"{overlap}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodexExecutionPolicy:
    mode: CodexExecutionMode = "non_interactive"
    sandbox: CodexSandbox = "workspace-write"
    approval_policy: CodexApprovalPolicy = "never"
    timeout_seconds: int = 1800
    model: str | None = None
    reasoning_effort: str | None = None
    web_search: bool = False
    ignore_user_config: bool = False
    ignore_rules: bool = False

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> CodexExecutionPolicy:
        policy = cls(
            mode=cast(
                CodexExecutionMode,
                str(data.get("mode", "non_interactive")),
            ),
            sandbox=cast(
                CodexSandbox,
                str(data.get("sandbox", "workspace-write")),
            ),
            approval_policy=cast(
                CodexApprovalPolicy,
                str(data.get("approval_policy", "never")),
            ),
            timeout_seconds=int(
                data.get("timeout_seconds", 1800)
            ),
            model=(
                str(data["model"])
                if data.get("model") is not None
                else None
            ),
            reasoning_effort=(
                str(data["reasoning_effort"])
                if data.get("reasoning_effort") is not None
                else None
            ),
            web_search=bool(
                data.get("web_search", False)
            ),
            ignore_user_config=bool(
                data.get("ignore_user_config", False)
            ),
            ignore_rules=bool(
                data.get("ignore_rules", False)
            ),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.mode not in {
            "non_interactive",
            "interactive",
            "manual",
        }:
            raise ValueError(
                f"Unsupported Codex execution mode: {self.mode}"
            )
        if self.sandbox not in {
            "read-only",
            "workspace-write",
            "danger-full-access",
        }:
            raise ValueError(
                f"Unsupported Codex sandbox: {self.sandbox}"
            )
        if self.approval_policy not in {
            "untrusted",
            "on-request",
            "never",
        }:
            raise ValueError(
                f"Unsupported approval policy: "
                f"{self.approval_policy}"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero"
            )
        if (
            self.mode == "non_interactive"
            and self.approval_policy != "never"
        ):
            raise ValueError(
                "Non-interactive Codex runs must not wait for "
                "human approval"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodexRunManifest:
    run_id: str
    project_root: str
    task: CodexTaskContract
    policy: CodexExecutionPolicy
    context_package: str | None = None
    agents_file: str | None = None
    prompt_file: str | None = None
    evidence_dir: str | None = None
    thread_id: str | None = None
    status: CodexRunStatus = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> CodexRunManifest:
        manifest = cls(
            run_id=str(data["run_id"]),
            project_root=str(data["project_root"]),
            task=CodexTaskContract.from_dict(
                _expect_dict(data["task"], "task")
            ),
            policy=CodexExecutionPolicy.from_dict(
                _expect_dict(data["policy"], "policy")
            ),
            context_package=_optional_string(
                data.get("context_package")
            ),
            agents_file=_optional_string(
                data.get("agents_file")
            ),
            prompt_file=_optional_string(
                data.get("prompt_file")
            ),
            evidence_dir=_optional_string(
                data.get("evidence_dir")
            ),
            thread_id=_optional_string(
                data.get("thread_id")
            ),
            status=cast(
                CodexRunStatus,
                str(data.get("status", "planned")),
            ),
            metadata=_expect_dict(
                data.get("metadata", {}),
                "metadata",
            ),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")

        project = Path(self.project_root).expanduser()
        if not project.is_absolute():
            raise ValueError(
                "project_root must be an absolute path"
            )

        if self.status not in {
            "planned",
            "prepared",
            "running",
            "completed",
            "failed",
            "manual_required",
        }:
            raise ValueError(
                f"Unsupported Codex run status: {self.status}"
            )

        if self.status in {
            "prepared",
            "running",
            "completed",
            "failed",
        }:
            required = {
                "agents_file": self.agents_file,
                "prompt_file": self.prompt_file,
                "evidence_dir": self.evidence_dir,
            }
            missing = sorted(
                key
                for key, value in required.items()
                if not value
            )
            if missing:
                raise ValueError(
                    f"Prepared Codex run is missing: {missing}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_root": self.project_root,
            "task": self.task.to_dict(),
            "policy": self.policy.to_dict(),
            "context_package": self.context_package,
            "agents_file": self.agents_file,
            "prompt_file": self.prompt_file,
            "evidence_dir": self.evidence_dir,
            "thread_id": self.thread_id,
            "status": self.status,
            "metadata": self.metadata,
        }


def _expect_dict(
    value: Any,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(
            f"{field_name} must contain a JSON object"
        )
    return value


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
