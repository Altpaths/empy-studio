"""Provider routing policy and a task-wide token ledger.

The routing module deliberately contains no provider implementation.  It keeps
the safety decisions (when a retry is allowed and how usage is charged) in a
small, testable product-core contract that can be shared by CLI, HTTP API, and
local-model adapters.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from ..token_usage import TokenUsage

RouteKind = Literal["direct", "omniroute", "openai_api", "local", "cli"]
RouteCostClass = Literal["free", "local", "account", "paid", "unknown"]
RouteFailureClass = Literal[
    "transient",
    "authentication",
    "quota",
    "unsupported",
    "policy",
    "mutation",
    "budget",
    "unknown",
]
RouteDecisionAction = Literal["switch", "stop"]
UsageState = Literal["reported", "unknown", "estimated"]


class _BudgetLike(Protocol):
    @property
    def total_limit_tokens(self) -> int:
        ...

    @property
    def planning_limit_tokens(self) -> int:
        ...

    @property
    def reserve_tokens(self) -> int:
        ...


@dataclass(frozen=True)
class ProviderRoute:
    """A route identity, never a secret or a credential value."""

    provider_id: str
    display_name: str
    kind: RouteKind
    model: str | None = None
    cost_class: RouteCostClass = "unknown"
    enabled: bool = True
    allow_paid: bool = False
    priority: int = 100
    credential_environment_variable: str | None = None

    def validate(self) -> None:
        if not self.provider_id.strip() or not self.display_name.strip():
            raise ValueError("provider route identity cannot be empty")
        if self.kind not in {"direct", "omniroute", "openai_api", "local", "cli"}:
            raise ValueError("unsupported provider route kind")
        if self.cost_class not in {"free", "local", "account", "paid", "unknown"}:
            raise ValueError("unsupported provider route cost class")
        if self.priority < 0:
            raise ValueError("provider route priority cannot be negative")
        if self.cost_class == "paid" and not self.allow_paid:
            raise ValueError("paid provider route requires explicit opt-in")
        if self.credential_environment_variable is not None:
            value = self.credential_environment_variable
            if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
                raise ValueError("credential environment variable must be a simple name")
            if value.startswith(("OPENAI_", "CODEX_")) and self.kind == "omniroute":
                raise ValueError("OmniRoute must use a dedicated credential name")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class RoutingPolicy:
    """Fail-closed route switching rules."""

    allow_paid: bool = False
    max_attempts: int = 2
    switch_only_without_mutation: bool = True
    require_reported_usage_for_switch: bool = True

    def validate(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not isinstance(self.allow_paid, bool):
            raise TypeError("allow_paid must be boolean")
        if not isinstance(self.switch_only_without_mutation, bool):
            raise TypeError("switch_only_without_mutation must be boolean")
        if not isinstance(self.require_reported_usage_for_switch, bool):
            raise TypeError("require_reported_usage_for_switch must be boolean")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class RouteAttempt:
    provider_id: str
    model: str | None
    attempt: int
    status: str
    failure_class: RouteFailureClass | None = None
    error_code: str | None = None
    changed_files: tuple[str, ...] = ()
    usage: TokenUsage | None = None
    usage_state: UsageState = "unknown"

    def validate(self) -> None:
        if not self.provider_id.strip() or self.attempt < 1:
            raise ValueError("route attempt identity is invalid")
        if self.usage_state not in {"reported", "unknown", "estimated"}:
            raise ValueError("unsupported route usage state")
        if self.usage is not None:
            self.usage.validate()

    def to_dict(self) -> dict[str, object]:
        self.validate()
        value = asdict(self)
        value["changed_files"] = list(self.changed_files)
        value["usage"] = self.usage.to_dict() if self.usage is not None else None
        return value


@dataclass(frozen=True)
class RouteReport:
    attempts: tuple[RouteAttempt, ...] = ()
    selected_provider_id: str | None = None
    switched: bool = False
    decision: RouteDecisionAction = "stop"
    reason: str = "No route attempt was made."

    def validate(self) -> None:
        if self.decision not in {"switch", "stop"}:
            raise ValueError("unsupported route decision")
        for item in self.attempts:
            item.validate()
        ids = [item.attempt for item in self.attempts]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError("route attempts must be contiguous")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "attempts": [item.to_dict() for item in self.attempts],
            "selected_provider_id": self.selected_provider_id,
            "switched": self.switched,
            "decision": self.decision,
            "reason": self.reason,
        }


def classify_route_failure(
    error_code: str | None,
    message: str | None = None,
) -> RouteFailureClass:
    """Map provider errors to conservative routing classes.

    Only a clear transient transport/rate signal is switchable.  Quota,
    billing, authentication, scope, and budget failures stay terminal.
    """

    code = (error_code or "").casefold()
    detail = (message or "").casefold()
    if code in {"budget_exceeded", "objective_not_met"}:
        return "budget" if code == "budget_exceeded" else "policy"
    if code in {"scope_violation", "dirty_worktree", "permission_denied", "sandbox_error"}:
        return "policy"
    if code in {"authentication_required", "unauthorized", "invalid_api_key"} or any(
        term in detail for term in ("unauthorized", "invalid api key", "not logged in", "sign in")
    ):
        return "authentication"
    if code in {"quota_exceeded", "billing_error", "insufficient_credit"} or any(
        term in detail for term in ("billing", "quota exhausted", "quota exceeded", "insufficient credit")
    ):
        return "quota"
    if code in {"rate_limited", "rate_limit_exceeded", "service_unavailable", "bad_gateway"}:
        return "transient"
    if code in {"network_error", "timeout", "launch_failed"}:
        return "transient"
    if any(term in detail for term in ("429", "rate limit", "temporarily unavailable", "503", "connection reset")):
        return "transient"
    if code in {"process_failed", "invalid_output", "installation_missing", "unavailable"}:
        return "unsupported" if "unsupported" in detail or "not found" in detail else "unknown"
    return "unknown"


@dataclass(frozen=True)
class LedgerDecision:
    allowed: bool
    reason: str
    reservation_tokens: int = 0
    remaining_tokens: int = 0


@dataclass(frozen=True)
class LedgerEntry:
    operation_id: str
    provider_id: str
    reserved_tokens: int
    charged_tokens: int
    usage_state: UsageState
    fresh_tokens: int | None
    cached_tokens: int | None
    total_tokens: int | None
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TaskLedgerSnapshot:
    schema_version: int
    total_limit_tokens: int
    fixed_commitment_tokens: int
    charged_tokens: int
    reserved_tokens: int
    remaining_tokens: int
    usage_complete: bool
    unknown_operation_ids: tuple[str, ...] = ()
    entries: tuple[LedgerEntry, ...] = ()

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported task ledger schema")
        if min(
            self.total_limit_tokens,
            self.fixed_commitment_tokens,
            self.charged_tokens,
            self.reserved_tokens,
            self.remaining_tokens,
        ) < 0:
            raise ValueError("task ledger values cannot be negative")
        expected_remaining = max(
            0,
            self.total_limit_tokens
            - self.fixed_commitment_tokens
            - self.charged_tokens
            - self.reserved_tokens,
        )
        if self.remaining_tokens != expected_remaining:
            raise ValueError("task ledger remaining capacity is inconsistent")
        for entry in self.entries:
            if entry.reserved_tokens < 0 or entry.charged_tokens < 0:
                raise ValueError("ledger entry token values cannot be negative")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            **asdict(self),
            "unknown_operation_ids": list(self.unknown_operation_ids),
            "entries": [item.to_dict() for item in self.entries],
        }


class TaskTokenLedger:
    """Thread-safe task-wide admission and usage accounting.

    ``fixed_commitment_tokens`` protects planning/reserve capacity.  A node
    reserves its complete locked allocation before a provider call; exact
    provider usage settles that reservation and releases the unused part.
    Unknown usage keeps the full reservation charged, so an opaque provider
    can never create free retry capacity by omission.
    """

    def __init__(self, *, total_limit_tokens: int, fixed_commitment_tokens: int = 0) -> None:
        if total_limit_tokens < 1 or fixed_commitment_tokens < 0:
            raise ValueError("invalid task ledger limits")
        if fixed_commitment_tokens > total_limit_tokens:
            raise ValueError("fixed commitment exceeds task limit")
        self.total_limit_tokens = total_limit_tokens
        self.fixed_commitment_tokens = fixed_commitment_tokens
        self._charged_tokens = 0
        self._reservations: dict[str, tuple[str, int]] = {}
        self._entries: list[LedgerEntry] = []
        self._unknown: set[str] = set()
        self._lock = threading.RLock()

    @classmethod
    def from_budget(cls, budget: _BudgetLike) -> TaskTokenLedger:
        total = int(budget.total_limit_tokens)
        fixed = int(budget.planning_limit_tokens) + int(budget.reserve_tokens)
        return cls(total_limit_tokens=total, fixed_commitment_tokens=fixed)

    def admit(self, operation_id: str, provider_id: str, requested_tokens: int) -> LedgerDecision:
        if not operation_id.strip() or not provider_id.strip():
            raise ValueError("ledger operation and provider IDs cannot be empty")
        if requested_tokens < 1:
            raise ValueError("requested_tokens must be positive")
        with self._lock:
            if operation_id in self._reservations:
                return LedgerDecision(False, "operation already has a reservation", 0, self._remaining())
            reserved = sum(value[1] for value in self._reservations.values())
            available = self.total_limit_tokens - self.fixed_commitment_tokens - self._charged_tokens - reserved
            if requested_tokens > available:
                return LedgerDecision(False, "task token ledger exhausted", 0, max(0, available))
            self._reservations[operation_id] = (provider_id, requested_tokens)
            return LedgerDecision(True, "task reservation accepted", requested_tokens, max(0, available - requested_tokens))

    def release_without_provider(self, operation_id: str, *, status: str = "blocked") -> None:
        with self._lock:
            provider_id, reserved = self._reservations.pop(operation_id, ("unknown", 0))
            if reserved:
                self._entries.append(LedgerEntry(operation_id, provider_id, reserved, 0, "reported", 0, 0, 0, status))

    def settle(
        self,
        operation_id: str,
        *,
        usage: TokenUsage | None,
        status: str,
        provider_id: str | None = None,
    ) -> LedgerEntry:
        with self._lock:
            reserved_provider, reserved = self._reservations.pop(operation_id, (provider_id or "unknown", 0))
            provider = provider_id or reserved_provider
            if usage is not None and usage.source == "provider":
                charged = max(0, usage.uncached_total)
                usage_state: UsageState = "reported"
            elif usage is not None and usage.source == "estimate":
                charged = max(reserved, usage.uncached_total)
                usage_state = "estimated"
            else:
                charged = reserved
                usage_state = "unknown"
                self._unknown.add(operation_id)
            self._charged_tokens += charged
            entry = LedgerEntry(
                operation_id=operation_id,
                provider_id=provider,
                reserved_tokens=reserved,
                charged_tokens=charged,
                usage_state=usage_state,
                fresh_tokens=usage.fresh_input if usage is not None else None,
                cached_tokens=usage.cached if usage is not None else None,
                total_tokens=usage.total if usage is not None else None,
                status=status,
            )
            self._entries.append(entry)
            return entry

    def _remaining(self) -> int:
        reserved = sum(value[1] for value in self._reservations.values())
        return max(0, self.total_limit_tokens - self.fixed_commitment_tokens - self._charged_tokens - reserved)

    def snapshot(self) -> TaskLedgerSnapshot:
        with self._lock:
            reserved = sum(value[1] for value in self._reservations.values())
            snapshot = TaskLedgerSnapshot(
                schema_version=1,
                total_limit_tokens=self.total_limit_tokens,
                fixed_commitment_tokens=self.fixed_commitment_tokens,
                charged_tokens=self._charged_tokens,
                reserved_tokens=reserved,
                remaining_tokens=self._remaining(),
                usage_complete=not self._unknown and not self._reservations,
                unknown_operation_ids=tuple(sorted(self._unknown)),
                entries=tuple(self._entries),
            )
            snapshot.validate()
            return snapshot

    @property
    def exhausted(self) -> bool:
        return self.snapshot().remaining_tokens == 0


def stable_route_key(route: ProviderRoute) -> str:
    """Return a redacted identity useful for cache/telemetry correlation."""

    route.validate()
    raw = f"{route.provider_id}|{route.kind}|{route.model or ''}|{route.cost_class}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
