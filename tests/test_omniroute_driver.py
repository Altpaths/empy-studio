from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_codex_production_driver import FakeProcess, request

from empy_studio.drivers.omniroute import CodexRouteConfig, OmniRouteCodexDriver


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://localhost/v1", "http://127.0.0.1/v1?x=1", "http://a@127.0.0.1/v1", "http://127.0.0.1/v1#x", "http://127.0.0.1/v2"])
def test_remote_or_ambiguous_url_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        CodexRouteConfig(base_url=url).validate()


@pytest.mark.parametrize("model", ["auto", "gpt-5", "oc/paid", "ollama/", "lmstudio/auto\n"])
def test_paid_or_implicit_model_rejected(model: str) -> None:
    with pytest.raises(ValueError):
        CodexRouteConfig(model=model).validate()


def test_paid_model_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError):
        CodexRouteConfig(model="gpt-5.6-mini").validate()
    paid = CodexRouteConfig(model="gpt-5.6-mini", allow_paid=True)
    paid.validate()
    assert CodexRouteConfig.from_dict(paid.to_dict()) == paid


def test_configuration_contains_only_key_name() -> None:
    config = CodexRouteConfig(mode="omniroute", env_key="OMNIROUTE_KEY")
    assert CodexRouteConfig.from_dict(config.to_dict()) == config
    with pytest.raises(ValueError):
        CodexRouteConfig(env_key="OPENAI_API_KEY").validate()


def setup_driver(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> OmniRouteCodexDriver:
    monkeypatch.setattr("empy_studio.drivers.codex.shutil.which", lambda _: "/fake/codex")
    def runner(command: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert "login" not in command
        assert "OPENAI_API_KEY" not in kw["env"]
        output = "codex 1.0" if command[-1] == "--version" else "--json --ephemeral --ignore-user-config --output-last-message"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
    driver = OmniRouteCodexDriver(route=CodexRouteConfig(mode="omniroute", env_key="OMNIROUTE_KEY"), command_runner=runner, **kwargs)
    monkeypatch.setattr(driver, "_models", lambda: {driver.route.model})
    return driver


def test_isolated_command_environment_and_cached_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "shared-secret")
    monkeypatch.setenv("OMNIROUTE_KEY", "route-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://remote.invalid")
    driver = setup_driver(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(driver, "_models", lambda: calls.append(1) or {driver.route.model})
    assert not driver.inspect_installation().ready
    assert calls == []
    assert driver.inspect_installation(refresh=True).ready
    assert driver.inspect_installation().ready
    assert len(calls) == 1
    env = driver._runtime_environment()
    assert "HTTPS_PROXY" not in env and "OPENAI_API_KEY" not in env
    assert not (Path(env["CODEX_HOME"]) / "auth.json").exists()
    command = driver.build_command(request(tmp_path), executable="codex", final_message_path=tmp_path / "final")
    joined = " ".join(command)
    assert "route-secret" not in joined and "shared-secret" not in joined
    assert 'wire_api="responses"' in joined
    assert "requires_openai_auth=false" in joined
    assert "request_max_retries=0" in joined and "stream_max_retries=0" in joined
    assert "--ignore-user-config" in command


def test_artifacts_and_callbacks_scrubbed_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNIROUTE_KEY", "route-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "shared-secret")
    output = tmp_path / "published"
    def factory(command: list[str], **kwargs: Any) -> FakeProcess:
        final = Path(command[command.index("--output-last-message") + 1])
        assert not final.is_relative_to(output)
        assert not output.exists()
        final.write_text("route-secret shared-secret")
        return FakeProcess(stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "route-secret"}}) + "\n", stderr="shared-secret")
    driver = setup_driver(monkeypatch, process_factory=factory)
    events: list[Any] = []
    result = driver.execute_streaming(request(tmp_path), node_id="node", artifact_dir=output, on_progress=events.append)
    assert result.status == "completed"
    assert "route-secret" not in str(events) + str(result)
    assert all("secret" not in p.read_text() for p in output.iterdir())


def test_model_disappearing_blocks_next_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    driver = setup_driver(monkeypatch, process_factory=lambda *a, **k: pytest.fail("must not launch"))
    assert driver.inspect_installation(refresh=True).ready
    monkeypatch.setattr(driver, "_models", lambda: set())
    result = driver.execute_streaming(request(tmp_path), node_id="n", artifact_dir=tmp_path / "out")
    assert result.status == "unavailable"


@pytest.mark.parametrize("payload", [[], "", "bad", None, 3])
def test_non_object_configuration_rejected(payload: Any) -> None:
    with pytest.raises(ValueError):
        CodexRouteConfig.from_dict(payload)


@pytest.mark.parametrize("field", ["mode", "base_url", "model", "env_key", "allow_paid"])
def test_constructor_invalid_types_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        CodexRouteConfig(**{field: []}).validate()  # type: ignore[arg-type]


@pytest.mark.parametrize(("detail", "code", "phrase"), [
    ("401 Unauthorized: Model oc/big-pickle is not supported", "process_failed", "unsupported"),
    ("401 Unauthorized quota_exceeded=false", "authentication_required", "dedicated route"),
    ("429 quota exhausted", "rate_limited", "free/local"),
    ("403 Forbidden", "permission_denied", "backend refused"),
    ("not logged in", "authentication_required", "dedicated route"),
])
def test_route_specific_error_messages(detail: str, code: str, phrase: str) -> None:
    actual, message = OmniRouteCodexDriver.map_error(detail, 1)
    assert actual == code
    assert phrase in message
    assert "codex login" not in message
