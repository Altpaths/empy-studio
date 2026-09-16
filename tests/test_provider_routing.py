from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from empy_studio.core import (
    DriverExecutionRequest,
    ProjectDescriptor,
    ProviderRoute,
    RoutingPolicy,
    TaskTokenLedger,
    classify_route_failure,
)
from empy_studio.drivers import (
    CodexInstallation,
    CodexNodeExecution,
    RoutedCodexNodeDriver,
)
from empy_studio.token_usage import TokenUsage


def _request(root: Path) -> DriverExecutionRequest:
    root.mkdir(parents=True, exist_ok=True)
    return DriverExecutionRequest(
        project=ProjectDescriptor(root=root, project_type="python", display_name="fixture"),
        task_id="task:node",
        prompt="bounded",
        allowed_paths=("src/app.py",),
        timeout_seconds=5,
        fresh_token_limit=100,
    )


def _installation(provider: str = "codex") -> CodexInstallation:
    return CodexInstallation(
        availability="available",
        executable=provider,
        version="1.0",
        authenticated=True,
        message="ready",
    )


def _result(
    root: Path,
    *,
    status: str = "failed",
    error_code: str | None = "rate_limited",
    error_message: str | None = "429 temporary",
    changed_files: tuple[str, ...] = (),
    usage: TokenUsage | None = None,
) -> CodexNodeExecution:
    result = CodexNodeExecution(
        node_id="node",
        task_id="task:node",
        status=status,  # type: ignore[arg-type]
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        return_code=0 if status == "completed" else 1,
        thread_id=None,
        summary="completed" if status == "completed" else "failed",
        changed_files=changed_files,
        event_count=1,
        events_path=str(root / "events.jsonl"),
        stderr_path=str(root / "stderr.log"),
        final_message_path=str(root / "final.md"),
        command_path=str(root / "command.json"),
        error_code=error_code,  # type: ignore[arg-type]
        error_message=error_message,
        usage=usage,
    )
    result.validate()
    return result


class FakeRouteDriver:
    supports_parallel_nodes = True

    def __init__(
        self,
        provider_id: str,
        results: list[CodexNodeExecution],
        mutation_path: Path | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.results = results
        self.mutation_path = mutation_path
        self.calls = 0
        self.requests = []

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        del refresh
        return _installation(self.provider_id)

    def execute_streaming(self, request, *, node_id, artifact_dir, on_progress=None):
        self.requests.append(request)
        del node_id, artifact_dir, on_progress
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if self.mutation_path is not None:
            self.mutation_path.parent.mkdir(parents=True, exist_ok=True)
            self.mutation_path.write_text("partial mutation\n", encoding="utf-8")
        return result

    def cancel(self) -> None:
        return None


class UnavailableRouteDriver(FakeRouteDriver):
    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        del refresh
        return CodexInstallation(
            availability="unavailable",
            executable=None,
            version=None,
            authenticated=False,
            message=f"{self.provider_id} is unavailable",
            remediation="Start the local route.",
            error_code="launch_failed",
        )


def _route(provider_id: str, *, cost_class: str = "local") -> ProviderRoute:
    return ProviderRoute(
        provider_id=provider_id,
        display_name=provider_id,
        kind="local",
        model=provider_id,
        cost_class=cost_class,  # type: ignore[arg-type]
        allow_paid=cost_class == "paid",
    )


def test_failure_classification_is_fail_closed() -> None:
    assert classify_route_failure("rate_limited", "429 temporary") == "transient"
    assert classify_route_failure("authentication_required", "401") == "authentication"
    assert classify_route_failure("process_failed", "quota exhausted") == "quota"
    assert classify_route_failure("quota_exceeded") == "quota"
    assert classify_route_failure("rate_limit_exceeded") == "transient"
    assert classify_route_failure("budget_exceeded", "fresh budget") == "budget"
    assert classify_route_failure("scope_violation", "outside ownership") == "policy"


def test_task_ledger_releases_exact_reported_usage_and_charges_unknown_conservatively() -> None:
    ledger = TaskTokenLedger(total_limit_tokens=100, fixed_commitment_tokens=10)
    assert ledger.admit("a", "one", 60).allowed
    ledger.settle(
        "a",
        usage=TokenUsage(input=20, output=5, cached=0, total=25, source="provider", provider="one"),
        status="completed",
    )
    assert ledger.snapshot().charged_tokens == 25
    assert ledger.snapshot().remaining_tokens == 65
    assert ledger.admit("b", "two", 60).allowed
    ledger.settle("b", usage=None, status="failed")
    snapshot = ledger.snapshot()
    assert snapshot.charged_tokens == 85
    assert snapshot.remaining_tokens == 5
    assert snapshot.usage_complete is False
    assert snapshot.unknown_operation_ids == ("b",)


def test_router_switches_only_after_reported_transient_failure_without_mutation(tmp_path: Path) -> None:
    primary = FakeRouteDriver(
        "primary",
        [_result(tmp_path / "one", usage=TokenUsage(input=20, output=2, total=22, source="provider", provider="primary"))],
    )
    fallback = FakeRouteDriver(
        "fallback",
        [_result(tmp_path / "two", status="completed", error_code=None, error_message=None,
                 usage=TokenUsage(input=10, output=3, total=13, source="provider", provider="fallback"))],
    )
    router = RoutedCodexNodeDriver(
        candidates=((_route("primary"), primary), (_route("fallback"), fallback)),
        policy=RoutingPolicy(max_attempts=2),
    )
    result = router.execute_streaming(_request(tmp_path / "project"), node_id="node", artifact_dir=tmp_path / "run")
    assert result.status == "completed"
    assert result.usage is not None and result.usage.uncached_total == 35
    assert router.last_report.switched is True
    assert [item.provider_id for item in router.last_report.attempts] == ["primary", "fallback"]
    assert fallback.requests[0].fresh_token_limit == 78


def test_router_never_switches_after_authentication_or_partial_mutation(tmp_path: Path) -> None:
    fallback = FakeRouteDriver("fallback", [_result(tmp_path / "fallback", status="completed", error_code=None, error_message=None)])
    for primary_result in (
        _result(tmp_path / "auth", error_code="authentication_required", error_message="401"),
        _result(tmp_path / "partial", changed_files=("src/app.py",)),
    ):
        primary = FakeRouteDriver("primary", [primary_result])
        router = RoutedCodexNodeDriver(
            candidates=((_route("primary"), primary), (_route("fallback"), fallback)),
            policy=RoutingPolicy(max_attempts=2),
        )
        result = router.execute_streaming(_request(tmp_path / "project"), node_id="node", artifact_dir=tmp_path / "run")
        assert result.status == "failed"
        assert fallback.calls == 0
        assert router.last_report.switched is False


def test_router_audits_unreported_worktree_mutation_before_switching(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    # A real repository is required for the mutation probe.  The command is
    # deliberately local and has no provider/network side effect.
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True)
    (project_root / "src").mkdir()
    (project_root / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=project_root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-qm", "fixture"],
        cwd=project_root,
        check=True,
    )
    primary = FakeRouteDriver(
        "primary",
        [_result(tmp_path / "primary", usage=TokenUsage(input=20, output=2, total=22, source="provider", provider="primary"))],
        mutation_path=project_root / "src" / "app.py",
    )
    fallback = FakeRouteDriver(
        "fallback",
        [_result(tmp_path / "fallback", status="completed", error_code=None, error_message=None)],
    )
    router = RoutedCodexNodeDriver(
        candidates=((_route("primary"), primary), (_route("fallback"), fallback)),
        policy=RoutingPolicy(max_attempts=2),
    )

    result = router.execute_streaming(
        _request(project_root),
        node_id="node",
        artifact_dir=tmp_path / "run",
    )

    assert result.status == "failed"
    assert fallback.calls == 0
    assert "mutation" in router.last_report.reason.lower()


def test_router_does_not_duplicate_unknown_usage(tmp_path: Path) -> None:
    primary = FakeRouteDriver("primary", [_result(tmp_path / "one", usage=None)])
    fallback = FakeRouteDriver("fallback", [_result(tmp_path / "two", status="completed", error_code=None, error_message=None)])
    router = RoutedCodexNodeDriver(
        candidates=((_route("primary"), primary), (_route("fallback"), fallback)),
        policy=RoutingPolicy(max_attempts=2),
    )
    result = router.execute_streaming(_request(tmp_path / "project"), node_id="node", artifact_dir=tmp_path / "run")
    assert result.status == "failed"
    assert fallback.calls == 0
    assert "not reported" in router.last_report.reason


def test_router_does_not_call_provider_again_after_all_preflight_failures(tmp_path: Path) -> None:
    primary = UnavailableRouteDriver("primary", [])
    fallback = UnavailableRouteDriver("fallback", [])
    router = RoutedCodexNodeDriver(
        candidates=((_route("primary"), primary), (_route("fallback"), fallback)),
        policy=RoutingPolicy(max_attempts=2),
    )

    result = router.execute_streaming(
        _request(tmp_path / "project"),
        node_id="node",
        artifact_dir=tmp_path / "run",
    )

    assert result.status == "unavailable"
    assert primary.calls == 0
    assert fallback.calls == 0
    assert len(router.last_report.attempts) == 2


def test_paid_route_requires_policy_opt_in() -> None:
    paid = _route("paid", cost_class="paid")
    with pytest.raises(ValueError):
        RoutedCodexNodeDriver(
            candidates=((paid, FakeRouteDriver("paid", [])),),
            policy=RoutingPolicy(allow_paid=False),
        )
