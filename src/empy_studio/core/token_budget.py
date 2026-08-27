from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Literal

from .context_selector import ContextPack, ContextSelection
from .planner import AgentRole, ExecutionPlan

BudgetPreset = Literal["economy", "standard", "extended"]
BudgetStatus = Literal["draft", "locked", "exhausted", "cancelled"]
RunStatus = Literal["ready", "running", "stopped", "completed"]
UsageKind = Literal["planning", "agent", "retry", "handoff"]

# Provider usage includes its system/tool harness and usually at least one
# replay after a tool call. The former budget counted only selected project
# excerpts, understating real fresh usage by 2x-6x in production.
PROVIDER_EXECUTION_OVERHEAD_TOKENS = 36_000


@dataclass(frozen=True)
class TokenBudgetPolicy:
    preset: BudgetPreset = "economy"
    planning_tokens: int = 3_000
    response_tokens_per_step: int = 2_500
    max_retries_per_step: int = 1
    retry_tokens_per_attempt: int = 1_200
    max_handoffs_per_step: int = 1
    handoff_tokens_per_event: int = 500
    reserve_tokens: int = 1_000
    hard_total_limit: int | None = None

    def validate(self) -> None:
        if self.preset not in {"economy", "standard", "extended"}:
            raise ValueError(f"unsupported token-budget preset: {self.preset}")
        positive_fields = {
            "planning_tokens": self.planning_tokens,
            "response_tokens_per_step": self.response_tokens_per_step,
            "retry_tokens_per_attempt": self.retry_tokens_per_attempt,
            "handoff_tokens_per_event": self.handoff_tokens_per_event,
            "reserve_tokens": self.reserve_tokens,
        }
        for name, value in positive_fields.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_retries_per_step < 0:
            raise ValueError("max_retries_per_step cannot be negative")
        if self.max_handoffs_per_step < 0:
            raise ValueError("max_handoffs_per_step cannot be negative")
        if self.hard_total_limit is not None and self.hard_total_limit < 1:
            raise ValueError("hard_total_limit must be positive")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def policy_for_preset(preset: BudgetPreset) -> TokenBudgetPolicy:
    if preset == "economy":
        return TokenBudgetPolicy(preset="economy")
    if preset == "standard":
        return TokenBudgetPolicy(
            preset="standard",
            planning_tokens=5_000,
            response_tokens_per_step=5_000,
            max_retries_per_step=2,
            retry_tokens_per_attempt=2_000,
            max_handoffs_per_step=2,
            handoff_tokens_per_event=800,
            reserve_tokens=2_000,
        )
    if preset == "extended":
        return TokenBudgetPolicy(
            preset="extended",
            planning_tokens=8_000,
            response_tokens_per_step=8_000,
            max_retries_per_step=3,
            retry_tokens_per_attempt=3_000,
            max_handoffs_per_step=3,
            handoff_tokens_per_event=1_200,
            reserve_tokens=4_000,
        )
    raise ValueError(f"unsupported token-budget preset: {preset}")


def estimate_tokens(text: str) -> int:
    """Return a deterministic provider-neutral token estimate.

    The estimate is intentionally conservative for non-ASCII text. Provider
    drivers can later replace this estimate with exact tokenizer usage without
    changing the budget contracts.
    """

    if not text:
        return 0
    ascii_count = sum(1 for character in text if ord(character) < 128)
    non_ascii_count = len(text) - ascii_count
    estimated = math.ceil(ascii_count / 4) + math.ceil(non_ascii_count / 2)
    return max(1, estimated)


@dataclass(frozen=True)
class AgentTokenAllocation:
    step_id: str
    agent_role: AgentRole
    context_tokens: int
    instruction_tokens: int
    response_tokens: int
    max_retries: int
    retry_tokens_per_attempt: int
    max_handoffs: int
    handoff_tokens_per_event: int
    base_limit_tokens: int
    retry_limit_tokens: int
    handoff_limit_tokens: int
    total_limit_tokens: int

    def validate(self) -> None:
        if not self.step_id:
            raise ValueError("allocation step_id cannot be empty")
        numeric_values = (
            self.context_tokens,
            self.instruction_tokens,
            self.response_tokens,
            self.retry_tokens_per_attempt,
            self.handoff_tokens_per_event,
            self.base_limit_tokens,
            self.retry_limit_tokens,
            self.handoff_limit_tokens,
            self.total_limit_tokens,
        )
        if any(value < 0 for value in numeric_values):
            raise ValueError("token allocation values cannot be negative")
        if self.max_retries < 0 or self.max_handoffs < 0:
            raise ValueError("retry and handoff counts cannot be negative")
        expected_base = (
            self.context_tokens
            + self.instruction_tokens
            + self.response_tokens
        )
        if self.base_limit_tokens != expected_base:
            raise ValueError("agent base limit is inconsistent")
        if self.retry_limit_tokens != (
            self.max_retries * self.retry_tokens_per_attempt
        ):
            raise ValueError("agent retry limit is inconsistent")
        if self.handoff_limit_tokens != (
            self.max_handoffs * self.handoff_tokens_per_event
        ):
            raise ValueError("agent handoff limit is inconsistent")
        expected_total = (
            self.base_limit_tokens
            + self.retry_limit_tokens
            + self.handoff_limit_tokens
        )
        if self.total_limit_tokens != expected_total:
            raise ValueError("agent total limit is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TokenBudget:
    schema_version: int
    budget_id: str
    plan_id: str
    selection_id: str
    task_id: str
    project_root: str
    created_at: str
    locked_at: str | None
    status: BudgetStatus
    preset: BudgetPreset
    planning_limit_tokens: int
    reserve_tokens: int
    total_limit_tokens: int
    estimated_context_tokens: int
    allocations: tuple[AgentTokenAllocation, ...]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported token-budget schema")
        if not self.budget_id or not self.plan_id or not self.selection_id:
            raise ValueError("token-budget identity cannot be empty")
        if self.status not in {"draft", "locked", "exhausted", "cancelled"}:
            raise ValueError(f"unsupported token-budget status: {self.status}")
        if self.status == "locked" and self.locked_at is None:
            raise ValueError("locked token budget requires locked_at")
        if self.planning_limit_tokens < 1 or self.reserve_tokens < 1:
            raise ValueError("planning and reserve limits must be positive")
        if not self.allocations:
            raise ValueError("token budget requires agent allocations")
        step_ids = {allocation.step_id for allocation in self.allocations}
        if len(step_ids) != len(self.allocations):
            raise ValueError("token-budget step allocations must be unique")
        for allocation in self.allocations:
            allocation.validate()
        measured_context = sum(
            allocation.context_tokens for allocation in self.allocations
        )
        if measured_context != self.estimated_context_tokens:
            raise ValueError("estimated context token count is inconsistent")
        measured_total = (
            self.planning_limit_tokens
            + self.reserve_tokens
            + sum(
                allocation.total_limit_tokens
                for allocation in self.allocations
            )
        )
        if measured_total != self.total_limit_tokens:
            raise ValueError("total token limit is inconsistent")

    def allocation_for_step(self, step_id: str) -> AgentTokenAllocation:
        for allocation in self.allocations:
            if allocation.step_id == step_id:
                return allocation
        raise KeyError(step_id)

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["allocations"] = [
            allocation.to_dict() for allocation in self.allocations
        ]
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _context_tokens(pack: ContextPack) -> int:
    total = estimate_tokens(pack.objective)
    for item in pack.files:
        total += estimate_tokens(item.relative_path)
        total += estimate_tokens(" ".join(item.reasons))
        total += estimate_tokens(item.content)
    return total


def build_token_budget(
    *,
    plan: ExecutionPlan,
    selection: ContextSelection,
    policy: TokenBudgetPolicy | None = None,
) -> TokenBudget:
    plan.validate()
    selection.validate()
    selected_policy = policy or policy_for_preset("economy")
    selected_policy.validate()

    if plan.status != "approved":
        raise ValueError("token budget requires an approved plan")
    if selection.plan_id != plan.plan_id:
        raise ValueError("context selection and plan do not match")
    if selection.task_id != plan.task_id:
        raise ValueError("context selection and task do not match")
    if selection.project_root != plan.project_root:
        raise ValueError("context selection and project do not match")

    packs_by_step = {pack.step_id: pack for pack in selection.packs}
    allocations: list[AgentTokenAllocation] = []
    for step in plan.steps:
        try:
            pack = packs_by_step[step.step_id]
        except KeyError as exc:
            raise ValueError(
                f"context selection is missing plan step: {step.step_id}"
            ) from exc
        context_tokens = _context_tokens(pack)
        instruction_tokens = PROVIDER_EXECUTION_OVERHEAD_TOKENS + estimate_tokens(
            f"{plan.summary}\n"
            f"{selection.project_brain.summary}\n"
            f"{step.title}\n"
            f"{step.objective}"
        )
        response_tokens = selected_policy.response_tokens_per_step
        base_limit = context_tokens + instruction_tokens + response_tokens
        retry_limit = (
            selected_policy.max_retries_per_step
            * selected_policy.retry_tokens_per_attempt
        )
        handoff_limit = (
            selected_policy.max_handoffs_per_step
            * selected_policy.handoff_tokens_per_event
        )
        allocations.append(
            AgentTokenAllocation(
                step_id=step.step_id,
                agent_role=step.suggested_agent,
                context_tokens=context_tokens,
                instruction_tokens=instruction_tokens,
                response_tokens=response_tokens,
                max_retries=selected_policy.max_retries_per_step,
                retry_tokens_per_attempt=(
                    selected_policy.retry_tokens_per_attempt
                ),
                max_handoffs=selected_policy.max_handoffs_per_step,
                handoff_tokens_per_event=(
                    selected_policy.handoff_tokens_per_event
                ),
                base_limit_tokens=base_limit,
                retry_limit_tokens=retry_limit,
                handoff_limit_tokens=handoff_limit,
                total_limit_tokens=(
                    base_limit + retry_limit + handoff_limit
                ),
            )
        )

    total_limit = (
        selected_policy.planning_tokens
        + selected_policy.reserve_tokens
        + sum(item.total_limit_tokens for item in allocations)
    )
    if (
        selected_policy.hard_total_limit is not None
        and total_limit > selected_policy.hard_total_limit
    ):
        raise ValueError(
            "derived token budget exceeds hard_total_limit; "
            "reduce context or choose smaller run limits"
        )

    fingerprint_payload = {
        "plan_id": plan.plan_id,
        "selection_id": selection.selection_id,
        "policy": selected_policy.to_dict(),
        "allocations": [item.to_dict() for item in allocations],
    }
    fingerprint = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    budget = TokenBudget(
        schema_version=1,
        budget_id=hashlib.sha256(fingerprint).hexdigest()[:20],
        plan_id=plan.plan_id,
        selection_id=selection.selection_id,
        task_id=plan.task_id,
        project_root=plan.project_root,
        created_at=_utc_now(),
        locked_at=None,
        status="draft",
        preset=selected_policy.preset,
        planning_limit_tokens=selected_policy.planning_tokens,
        reserve_tokens=selected_policy.reserve_tokens,
        total_limit_tokens=total_limit,
        estimated_context_tokens=sum(
            item.context_tokens for item in allocations
        ),
        allocations=tuple(allocations),
    )
    budget.validate()
    return budget


def lock_token_budget(budget: TokenBudget) -> TokenBudget:
    budget.validate()
    if budget.status == "locked":
        return budget
    if budget.status != "draft":
        raise ValueError("only draft token budgets can be locked")
    locked = replace(
        budget,
        status="locked",
        locked_at=_utc_now(),
    )
    locked.validate()
    return locked


@dataclass(frozen=True)
class StepBudgetUsage:
    step_id: str
    agent_tokens: int = 0
    retry_tokens: int = 0
    handoff_tokens: int = 0
    retries: int = 0
    handoffs: int = 0
    stopped: bool = False
    stop_reason: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.agent_tokens + self.retry_tokens + self.handoff_tokens


@dataclass(frozen=True)
class BudgetEvent:
    event_id: str
    created_at: str
    kind: UsageKind
    step_id: str | None
    requested_tokens: int
    charged_tokens: int
    allowed: bool
    reason: str


@dataclass(frozen=True)
class BudgetRunState:
    schema_version: int
    budget_id: str
    status: RunStatus
    total_tokens_used: int
    planning_tokens_used: int
    steps: tuple[StepBudgetUsage, ...]
    events: tuple[BudgetEvent, ...]
    stop_reason: str | None = None

    def usage_for_step(self, step_id: str) -> StepBudgetUsage:
        for usage in self.steps:
            if usage.step_id == step_id:
                return usage
        raise KeyError(step_id)


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    state: BudgetRunState
    remaining_total_tokens: int
    remaining_step_tokens: int | None


def start_budget_run(budget: TokenBudget) -> BudgetRunState:
    budget.validate()
    if budget.status != "locked":
        raise ValueError("token budget must be locked before a run can start")
    return BudgetRunState(
        schema_version=1,
        budget_id=budget.budget_id,
        status="ready",
        total_tokens_used=0,
        planning_tokens_used=0,
        steps=tuple(
            StepBudgetUsage(step_id=allocation.step_id)
            for allocation in budget.allocations
        ),
        events=(),
    )


def _replace_step(
    state: BudgetRunState,
    updated: StepBudgetUsage,
) -> tuple[StepBudgetUsage, ...]:
    return tuple(
        updated if item.step_id == updated.step_id else item
        for item in state.steps
    )


def _event(
    *,
    state: BudgetRunState,
    kind: UsageKind,
    step_id: str | None,
    requested_tokens: int,
    charged_tokens: int,
    allowed: bool,
    reason: str,
) -> BudgetEvent:
    payload = (
        f"{state.budget_id}:{len(state.events)}:{kind}:{step_id}:"
        f"{requested_tokens}:{allowed}:{reason}"
    )
    return BudgetEvent(
        event_id=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20],
        created_at=_utc_now(),
        kind=kind,
        step_id=step_id,
        requested_tokens=requested_tokens,
        charged_tokens=charged_tokens,
        allowed=allowed,
        reason=reason,
    )


def _decision(
    *,
    budget: TokenBudget,
    state: BudgetRunState,
    allowed: bool,
    reason: str,
    step_id: str | None,
) -> BudgetDecision:
    remaining_step: int | None = None
    if step_id is not None:
        allocation = budget.allocation_for_step(step_id)
        usage = state.usage_for_step(step_id)
        remaining_step = max(
            0,
            allocation.total_limit_tokens - usage.total_tokens,
        )
    return BudgetDecision(
        allowed=allowed,
        reason=reason,
        state=state,
        remaining_total_tokens=max(
            0,
            budget.total_limit_tokens - state.total_tokens_used,
        ),
        remaining_step_tokens=remaining_step,
    )


def apply_budget_usage(
    *,
    budget: TokenBudget,
    state: BudgetRunState,
    kind: UsageKind,
    requested_tokens: int,
    step_id: str | None = None,
) -> BudgetDecision:
    budget.validate()
    if budget.status != "locked":
        raise ValueError("token budget must be locked before usage is recorded")
    if state.budget_id != budget.budget_id:
        raise ValueError("run state and token budget do not match")
    if requested_tokens < 1:
        raise ValueError("requested_tokens must be positive")
    if state.status in {"stopped", "completed"}:
        return _decision(
            budget=budget,
            state=state,
            allowed=False,
            reason=state.stop_reason or "run is not active",
            step_id=step_id,
        )

    next_total = state.total_tokens_used + requested_tokens
    if next_total > budget.total_limit_tokens:
        event = _event(
            state=state,
            kind=kind,
            step_id=step_id,
            requested_tokens=requested_tokens,
            charged_tokens=0,
            allowed=False,
            reason="total token budget exhausted",
        )
        stopped = replace(
            state,
            status="stopped",
            events=state.events + (event,),
            stop_reason="total token budget exhausted",
        )
        return _decision(
            budget=budget,
            state=stopped,
            allowed=False,
            reason="total token budget exhausted",
            step_id=step_id,
        )

    if kind == "planning":
        if step_id is not None:
            raise ValueError("planning usage cannot have a step_id")
        if (
            state.planning_tokens_used + requested_tokens
            > budget.planning_limit_tokens
        ):
            event = _event(
                state=state,
                kind=kind,
                step_id=None,
                requested_tokens=requested_tokens,
                charged_tokens=0,
                allowed=False,
                reason="planning token limit reached",
            )
            stopped = replace(
                state,
                status="stopped",
                events=state.events + (event,),
                stop_reason="planning token limit reached",
            )
            return _decision(
                budget=budget,
                state=stopped,
                allowed=False,
                reason="planning token limit reached",
                step_id=None,
            )
        event = _event(
            state=state,
            kind=kind,
            step_id=None,
            requested_tokens=requested_tokens,
            charged_tokens=requested_tokens,
            allowed=True,
            reason="planning usage accepted",
        )
        accepted = replace(
            state,
            status="running",
            total_tokens_used=next_total,
            planning_tokens_used=(
                state.planning_tokens_used + requested_tokens
            ),
            events=state.events + (event,),
        )
        return _decision(
            budget=budget,
            state=accepted,
            allowed=True,
            reason="planning usage accepted",
            step_id=None,
        )

    if step_id is None:
        raise ValueError(f"{kind} usage requires a step_id")
    allocation = budget.allocation_for_step(step_id)
    usage = state.usage_for_step(step_id)
    if usage.stopped:
        return _decision(
            budget=budget,
            state=state,
            allowed=False,
            reason=usage.stop_reason or "step is stopped",
            step_id=step_id,
        )

    reason = "usage accepted"
    updated_usage = usage
    if kind == "agent":
        if usage.agent_tokens + requested_tokens > allocation.base_limit_tokens:
            reason = "agent token limit reached"
        else:
            updated_usage = replace(
                usage,
                agent_tokens=usage.agent_tokens + requested_tokens,
            )
    elif kind == "retry":
        if usage.retries >= allocation.max_retries:
            reason = "retry limit reached"
        elif (
            usage.retry_tokens + requested_tokens
            > allocation.retry_limit_tokens
        ):
            reason = "retry token limit reached"
        else:
            updated_usage = replace(
                usage,
                retries=usage.retries + 1,
                retry_tokens=usage.retry_tokens + requested_tokens,
            )
    elif kind == "handoff":
        if usage.handoffs >= allocation.max_handoffs:
            reason = "handoff limit reached"
        elif (
            usage.handoff_tokens + requested_tokens
            > allocation.handoff_limit_tokens
        ):
            reason = "handoff token limit reached"
        else:
            updated_usage = replace(
                usage,
                handoffs=usage.handoffs + 1,
                handoff_tokens=usage.handoff_tokens + requested_tokens,
            )

    allowed = updated_usage != usage
    if not allowed:
        stopped_usage = replace(
            usage,
            stopped=True,
            stop_reason=reason,
        )
        event = _event(
            state=state,
            kind=kind,
            step_id=step_id,
            requested_tokens=requested_tokens,
            charged_tokens=0,
            allowed=False,
            reason=reason,
        )
        denied = replace(
            state,
            status="running",
            steps=_replace_step(state, stopped_usage),
            events=state.events + (event,),
        )
        return _decision(
            budget=budget,
            state=denied,
            allowed=False,
            reason=reason,
            step_id=step_id,
        )

    event = _event(
        state=state,
        kind=kind,
        step_id=step_id,
        requested_tokens=requested_tokens,
        charged_tokens=requested_tokens,
        allowed=True,
        reason=reason,
    )
    accepted = replace(
        state,
        status="running",
        total_tokens_used=next_total,
        steps=_replace_step(state, updated_usage),
        events=state.events + (event,),
    )
    return _decision(
        budget=budget,
        state=accepted,
        allowed=True,
        reason=reason,
        step_id=step_id,
    )
