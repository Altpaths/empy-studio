"""Safe routing between Codex-compatible drivers.

The router is intentionally conservative: a provider can be replaced only
after a transient failure with no observed file mutation and reported usage.
It never retries a budget, authentication, quota, scope, or partial-change
failure.
"""
from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from empy_studio.core import (
    DriverExecutionRequest,
    DriverInspection,
    ProviderRoute,
    RouteAttempt,
    RouteReport,
    RoutingPolicy,
    UsageState,
    classify_route_failure,
)
from empy_studio.token_usage import TokenUsage

from .codex import (
    CodexInstallation,
    CodexNodeExecution,
)


class CodexCompatibleDriver(Protocol):
    @property
    def provider_id(self) -> str:
        ...

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        ...

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        ...

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress: Any = None,
    ) -> CodexNodeExecution:
        ...

    def cancel(self) -> None:
        ...


class RouteDriverCandidate(Protocol):
    route: ProviderRoute
    driver: CodexCompatibleDriver


class _Candidate:
    def __init__(self, route: ProviderRoute, driver: CodexCompatibleDriver) -> None:
        route.validate()
        self.route = route
        self.driver = driver


class RoutedCodexNodeDriver:
    """Execute a node through an ordered, explicitly configured route list."""

    def __init__(
        self,
        *,
        candidates: tuple[tuple[ProviderRoute, CodexCompatibleDriver], ...],
        policy: RoutingPolicy | None = None,
    ) -> None:
        if not candidates:
            raise ValueError("at least one provider route is required")
        self.policy = policy or RoutingPolicy()
        self.policy.validate()
        self._candidates = tuple(_Candidate(route, driver) for route, driver in candidates)
        if len({item.route.provider_id for item in self._candidates}) != len(self._candidates):
            raise ValueError("provider route IDs must be unique")
        for item in self._candidates:
            if item.route.cost_class == "paid" and not (self.policy.allow_paid and item.route.allow_paid):
                raise ValueError("paid route is not allowed by the routing policy")
        self._selected_index = 0
        self._last_report = RouteReport(reason="No route attempt has started.")

    @property
    def provider_id(self) -> str:
        return self._candidates[self._selected_index].route.provider_id

    @property
    def display_name(self) -> str:
        return self._candidates[self._selected_index].route.display_name

    @property
    def supports_parallel_nodes(self) -> bool:
        return bool(getattr(self._candidates[self._selected_index].driver, "supports_parallel_nodes", False))

    @property
    def last_report(self) -> RouteReport:
        return self._last_report

    @staticmethod
    def _unavailable_result(
        *,
        request: DriverExecutionRequest,
        node_id: str,
        artifact_dir: Path,
        installation: CodexInstallation,
    ) -> CodexNodeExecution:
        timestamp = datetime.now(timezone.utc).isoformat()
        result = CodexNodeExecution(
            node_id=node_id,
            task_id=request.task_id,
            status="unavailable",
            started_at=timestamp,
            finished_at=timestamp,
            return_code=None,
            thread_id=None,
            summary="Provider route preflight did not produce an executable candidate.",
            changed_files=(),
            event_count=0,
            events_path=str(artifact_dir / "events.jsonl"),
            stderr_path=str(artifact_dir / "stderr.log"),
            final_message_path=str(artifact_dir / "final-message.md"),
            command_path=str(artifact_dir / "command.json"),
            error_code=installation.terminal_error_code,
            error_message=installation.message
            + (f" {installation.remediation}" if installation.remediation else ""),
        )
        result.validate()
        return result

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        first_failure: CodexInstallation | None = None
        for index, candidate in enumerate(self._candidates):
            if not candidate.route.enabled:
                continue
            if candidate.route.cost_class == "paid" and not self.policy.allow_paid:
                continue
            installation = candidate.driver.inspect_installation(refresh=refresh)
            if first_failure is None:
                first_failure = installation
            if installation.ready:
                self._selected_index = index
                return installation
        if first_failure is None:
            raise RuntimeError("no enabled provider route is available")
        return first_failure

    def inspect(self, *, refresh: bool = False) -> DriverInspection:
        """Inspect the first allowed route, preserving the normal driver shape."""
        first: DriverInspection | None = None
        for index, candidate in enumerate(self._candidates):
            if not candidate.route.enabled or (
                candidate.route.cost_class == "paid" and not self.policy.allow_paid
            ):
                continue
            inspection = candidate.driver.inspect(refresh=refresh)
            if first is None:
                first = inspection
            if inspection.ready:
                self._selected_index = index
                return inspection
        if first is None:
            raise RuntimeError("no enabled provider route is available")
        return first

    @staticmethod
    def _git_status(root: Path) -> frozenset[str] | None:
        try:
            completed = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return frozenset(
            line[3:] if len(line) > 3 else line
            for line in completed.stdout.splitlines()
            if line.strip()
        )

    def execute_streaming(
        self,
        request: DriverExecutionRequest,
        *,
        node_id: str,
        artifact_dir: str | Path,
        on_progress: Any = None,
    ) -> CodexNodeExecution:
        request.validate()
        active = [
            item for item in self._candidates
            if item.route.enabled
            and (item.route.cost_class != "paid" or self.policy.allow_paid)
        ]
        if not active:
            raise RuntimeError("no enabled provider route is allowed by policy")

        # Keep the single-route artifact layout byte-for-byte compatible with
        # existing releases.  Attempt subdirectories are used only when a
        # route list is configured.
        multi_route = len(active) > 1
        attempts: list[RouteAttempt] = []
        usages: list[TokenUsage] = []
        selected_result: CodexNodeExecution | None = None
        selected_index = self._selected_index
        report_reason = "The primary route completed or produced a terminal failure."
        initial_status = self._git_status(request.project.root)
        mutation_audit_safe = initial_status == frozenset()

        for attempt_number, candidate in enumerate(active[: self.policy.max_attempts], start=1):
            index = self._candidates.index(candidate)
            self._selected_index = index
            consumed_tokens = sum(item.uncached_total for item in usages)
            remaining_limit = (
                request.fresh_token_limit - consumed_tokens
                if request.fresh_token_limit is not None
                else None
            )
            if remaining_limit is not None and remaining_limit < 1:
                report_reason = (
                    "Route stopped because the shared node token allocation was "
                    "already consumed by an earlier attempt."
                )
                break
            installation = candidate.driver.inspect_installation(refresh=True)
            if not installation.ready:
                attempts.append(
                    RouteAttempt(
                        provider_id=candidate.route.provider_id,
                        model=candidate.route.model,
                        attempt=attempt_number,
                        status="failed",
                        failure_class="unsupported",
                        error_code=installation.error_code,
                        usage_state="unknown",
                    )
                )
                report_reason = installation.message
                continue

            destination = Path(artifact_dir)
            if multi_route:
                destination = destination / f"attempt-{attempt_number:02d}-{candidate.route.provider_id}"
            attempt_request = (
                request
                if remaining_limit is None or remaining_limit == request.fresh_token_limit
                else replace(request, fresh_token_limit=remaining_limit)
            )
            result = candidate.driver.execute_streaming(
                attempt_request,
                node_id=node_id,
                artifact_dir=destination,
                on_progress=on_progress,
            )
            if mutation_audit_safe:
                after_status = self._git_status(request.project.root)
                if after_status is not None and initial_status is not None:
                    changed_by_attempt = after_status - initial_status
                    if changed_by_attempt:
                        result = replace(
                            result,
                            changed_files=tuple(
                                sorted(set(result.changed_files) | changed_by_attempt)
                            ),
                        )
            usage = result.usage
            if usage is not None:
                usages.append(usage)
            usage_state: UsageState = (
                "reported"
                if usage is not None and usage.source == "provider"
                else ("estimated" if usage is not None else "unknown")
            )
            failure_class = (
                None
                if result.status == "completed"
                else classify_route_failure(result.error_code, result.error_message or result.summary)
            )
            attempts.append(
                RouteAttempt(
                    provider_id=candidate.route.provider_id,
                    model=candidate.route.model,
                    attempt=attempt_number,
                    status=result.status,
                    failure_class=failure_class,
                    error_code=result.error_code,
                    changed_files=tuple(result.changed_files),
                    usage=usage,
                    usage_state=usage_state,
                )
            )
            selected_result = result
            if result.status == "completed":
                selected_index = index
                report_reason = "Route completed."
                break

            # A mutation makes a provider switch unsafe even when the provider
            # claims a transient error.  Verification must inspect this exact
            # worktree first.
            if result.changed_files:
                report_reason = "Route stopped after a partial file mutation; Verification must run before recovery."
                break
            if initial_status is not None and not mutation_audit_safe:
                report_reason = (
                    "Route stopped because the worktree was already dirty; "
                    "Empy cannot prove that a fallback is mutation-safe."
                )
                break
            if failure_class != "transient":
                report_reason = result.error_message or result.summary
                break
            if self.policy.require_reported_usage_for_switch and usage_state != "reported":
                report_reason = "Route stopped because transient failure usage was not reported."
                break
            if attempt_number >= self.policy.max_attempts:
                report_reason = "Transient route failure exhausted the bounded attempt count."
                break
            report_reason = "Transient provider failure with no mutation; trying the next explicitly configured route."

        if selected_result is None:
            # All routes failed deterministic preflight. Return a local,
            # provider-free unavailable result. Calling a provider again here
            # would exceed the bounded attempt count and could repeat a costly
            # gateway request after preflight already proved it unusable.
            candidate = active[0]
            self._selected_index = self._candidates.index(candidate)
            installation = candidate.driver.inspect_installation(refresh=False)
            destination = (
                Path(artifact_dir) / f"attempt-01-{candidate.route.provider_id}"
                if multi_route
                else Path(artifact_dir)
            )
            selected_result = self._unavailable_result(
                request=request,
                node_id=node_id,
                artifact_dir=destination,
                installation=installation,
            )

        if len(usages) > 1:
            aggregate = TokenUsage.aggregate(usages, provider="codex")
            if aggregate is not None:
                selected_result = replace(selected_result, usage=aggregate)
        self._selected_index = selected_index
        switched = len({item.provider_id for item in attempts if item.status != "skipped"}) > 1
        self._last_report = RouteReport(
            attempts=tuple(attempts),
            selected_provider_id=self._candidates[self._selected_index].route.provider_id,
            switched=switched,
            decision="switch" if switched else "stop",
            reason=report_reason,
        )
        self._last_report.validate()
        return selected_result

    def cancel(self) -> None:
        for candidate in self._candidates:
            candidate.driver.cancel()
