"""Durable bounded recovery decisions; no provider or filesystem dependencies."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecoveryPolicy:
    max_attempts: int = 3
    max_minutes: int = 30
    max_fresh_tokens: int = 500_000

    def __post_init__(self) -> None:
        for name, minimum, maximum in (
            ("max_attempts", 0, 10), ("max_minutes", 1, 240),
            ("max_fresh_tokens", 1_000, 5_000_000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")


_VOLATILE_FAILURE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # UUIDs and provider/run identifiers are regenerated on every attempt.
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE), "<id>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE), "<id>"),
    # ISO timestamps and Unix millisecond/second stamps make otherwise equal
    # failures look different after a restart.
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b", re.IGNORECASE), "<timestamp>"),
    (re.compile(r"\b\d{10,13}\b"), "<timestamp>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:seconds?|milliseconds?|ms|s)\b", re.IGNORECASE), "<duration>"),
    (re.compile(r"\b(?:line|column|col)\s*[:=]?\s*\d+\b", re.IGNORECASE), "<location>"),
    # Temporary roots and worktree names change between runs. Keep the error
    # text while removing the volatile path itself.
    (re.compile(r"(?<!\w)(?:[a-z]:[\\/]|/)[^\s'\"]+", re.IGNORECASE), "<path>"),
)


def _normalise_failure_context(context: str) -> str:
    """Return a stable failure description suitable for cross-run matching."""

    stable = unicodedata.normalize("NFKC", context or "").casefold()
    for pattern, replacement in _VOLATILE_FAILURE_PATTERNS:
        stable = pattern.sub(replacement, stable)
    # Repeated provider output can be very large. The beginning and end both
    # contain useful check identity, so retain a bounded slice of each.
    stable = re.sub(r"\s+", " ", stable).strip()
    if len(stable) > 8000:
        stable = stable[:6000] + " … " + stable[-2000:]
    return stable


def failure_fingerprint(context: str) -> str:
    """Ignore volatile run data while retaining check identity and errors."""

    return hashlib.sha256(_normalise_failure_context(context).encode()).hexdigest()


@dataclass
class RecoveryState:
    policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)
    original_request: str = ""
    task_id: str | None = None
    started_at: float | None = None
    attempts: int = 0
    status: str = "ready"
    stop_reason: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    accounted_runs: list[str] = field(default_factory=list)
    known_fresh_tokens: int = 0
    reserved_unknown_tokens: int = 0
    usage_complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, value: Any) -> RecoveryState:
        if not isinstance(value, Mapping) or value.get("schema_version") != 1:
            return cls()
        try:
            raw_policy = value.get("policy")
            if not isinstance(raw_policy, Mapping):
                raise TypeError("Invalid recovery policy")
            policy = RecoveryPolicy(**dict(raw_policy))
            fields = {
                key: value[key]
                for key in cls.__dataclass_fields__
                if key in value and key != "policy"
            }
            result = cls(policy=policy, **fields)
            if (
                type(result.attempts) is not int
                or not 0 <= result.attempts <= policy.max_attempts
                or result.status not in {"ready", "running", "stopped", "verified"}
                or not isinstance(result.history, list)
                or not isinstance(result.accounted_runs, list)
                or len(set(result.accounted_runs)) != len(result.accounted_runs)
                or not all(isinstance(item, str) and item.strip() for item in result.accounted_runs)
                or any(
                    type(getattr(result, name)) is not int
                    or getattr(result, name) < 0
                    for name in ("known_fresh_tokens", "reserved_unknown_tokens")
                )
                or not isinstance(result.original_request, str)
                or result.task_id is not None
                and (not isinstance(result.task_id, str) or not result.task_id.strip())
                or result.started_at is not None
                and type(result.started_at) not in {int, float}
                or not isinstance(result.usage_complete, bool)
                or result.stop_reason is not None
                and not isinstance(result.stop_reason, str)
            ):
                raise ValueError("Invalid recovery state")
            for row in result.history:
                if not isinstance(row, Mapping):
                    raise TypeError("Invalid recovery history")
                if (
                    not isinstance(row.get("fingerprint"), str)
                    or not isinstance(row.get("checkpoint"), str)
                    or not isinstance(row.get("owner"), str)
                    or type(row.get("cycle")) is not int
                    or row["cycle"] < 0
                    or row.get("progress") not in {"new_failure", "unchanged_failure"}
                    or row.get("strategy") not in {"targeted_fix", "inspect_contract_and_root_cause"}
                ):
                    raise ValueError("Invalid recovery history")
            return result
        except (TypeError, ValueError, KeyError):
            result = cls()
            result.stop("invalid_state: Saved recovery state needs review before execution.")
            return result

    def account(self, run_id: str, fresh_tokens: int | None, reserved_tokens: int = 0, *, complete: bool = True) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id cannot be empty")
        if fresh_tokens is not None and (type(fresh_tokens) is not int or fresh_tokens < 0):
            raise ValueError("fresh_tokens must be a non-negative integer or None")
        if type(reserved_tokens) is not int or reserved_tokens < 0:
            raise ValueError("reserved_tokens must be a non-negative integer")
        if not isinstance(complete, bool):
            raise TypeError("complete must be a boolean")
        if run_id in self.accounted_runs:
            return
        self.accounted_runs.append(run_id)
        if fresh_tokens is not None:
            self.known_fresh_tokens += fresh_tokens
        if fresh_tokens is None or not complete:
            self.usage_complete = False
            self.reserved_unknown_tokens += reserved_tokens

    def remaining_seconds(self, now: float | None = None) -> float:
        elapsed = 0.0 if self.started_at is None else max(0.0, (time.time() if now is None else now) - self.started_at)
        return max(0.0, self.policy.max_minutes * 60 - elapsed)

    def limit_reason(self, *, planned_tokens: int = 0, now: float | None = None, check_attempts: bool = True) -> str | None:
        if check_attempts and self.attempts >= self.policy.max_attempts:
            return "attempts_exhausted: Repair cycle allowance exhausted; review the recorded failures."
        if self.remaining_seconds(now) <= 0:
            return "time_exhausted: Workflow time allowance exhausted; review the last checkpoint."
        if self.known_fresh_tokens + self.reserved_unknown_tokens + planned_tokens > self.policy.max_fresh_tokens:
            return "budget_exhausted: Remaining workflow fresh-token allowance cannot cover another run."
        return None

    def stop(self, reason: str) -> None:
        self.status = "stopped"
        self.stop_reason = reason

    def record_failure(self, context: str, checkpoint: str, owner: str) -> str | None:
        fingerprint = failure_fingerprint(context)
        repeated = any(row.get("fingerprint") == fingerprint for row in self.history)
        repeat_count = sum(row.get("fingerprint") == fingerprint for row in self.history)
        self.history.append({
            "cycle": self.attempts, "fingerprint": fingerprint,
            "checkpoint": checkpoint, "owner": owner, "context": context[:4000],
            "progress": "unchanged_failure" if repeated else "new_failure",
            "strategy": "inspect_contract_and_root_cause" if repeated else "targeted_fix",
            "repeat_count": repeat_count,
        })
        # Different patches that leave the same failing check are not verified
        # progress, including A -> B -> A cycles after a partial repair.
        if repeated:
            return "no_progress: The same failure remains after repair; inspect its contract and root cause before retrying."
        return None

    def begin(self) -> None:
        self.attempts += 1
        self.status = "running"
        self.stop_reason = None
        if self.started_at is None:
            self.started_at = time.time()


def external_block(context: str) -> str | None:
    normalized = context.casefold()
    groups = {
        "credentials": ("not authenticated", "authentication required", "api key", "unauthorized", "login required", "sign in", "invalid_api_key"),
        "provider": ("unsupported model", "unsupported by the local gateway", "responses endpoint is unsupported", "model not found", "no compatible model"),
        "environment": ("permission denied", "access is denied", "dependency preparation blocked", "enospc", "network is unreachable", "connection refused", "command not found"),
    }
    for kind, markers in groups.items():
        if any(marker in normalized for marker in markers):
            return f"{kind}: Resolve the recorded external prerequisite, then explicitly resume this workflow."
    return None
