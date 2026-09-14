"""Explicit free/local Codex routing, isolated from the user's Codex account."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from empy_studio.core import DriverExecutionRequest

from .codex import CodexDriver, CodexErrorCode, CodexInstallation, CodexNodeExecution, ProgressCallback

FREE_MODELS = frozenset({"oc/north-mini-code-free", "oc/big-pickle"})
_NOAUTH_KEY = "EMPY_OMNIROUTE_NOAUTH"


@dataclass(frozen=True)
class CodexRouteConfig:
    mode: Literal["direct", "omniroute"] = "direct"
    base_url: str = "http://127.0.0.1:20129/v1"
    model: str = "oc/north-mini-code-free"
    env_key: str | None = None
    allow_paid: bool = False

    def validate(self) -> None:
        if (not all(isinstance(v, str) for v in (self.mode, self.base_url, self.model))
                or self.env_key is not None and not isinstance(self.env_key, str)
                or type(self.allow_paid) is not bool):
            raise ValueError("Route settings must be strings")
        if self.mode not in {"direct", "omniroute"}:
            raise ValueError("Unsupported Codex route mode")
        url = urlsplit(self.base_url)
        try:
            local = ipaddress.ip_address(url.hostname or "").is_loopback
            port = url.port
        except ValueError as exc:
            raise ValueError("Route requires a literal loopback IP") from exc
        if (self.base_url != self.base_url.strip() or any(ord(c) < 32 for c in self.base_url)
                or not local or url.scheme != "http" or url.path != "/v1"
                or url.username is not None or url.password is not None
                or url.query or url.fragment or port == 0):
            raise ValueError("Route requires an HTTP literal loopback URL ending in /v1")
        local_model = re.fullmatch(
            r"(?:ollama|lmstudio)/[A-Za-z0-9][A-Za-z0-9_.:/-]*", self.model
        ) is not None
        explicit_model = re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", self.model
        ) is not None
        if self.model in {"auto", "default"} or not explicit_model:
            raise ValueError("Choose one explicit model ID; automatic selection is disabled")
        if self.model not in FREE_MODELS and not local_model and not self.allow_paid:
            raise ValueError("Only free/local models are allowed unless paid routing is explicitly enabled")
        if self.env_key is not None and (
            not re.fullmatch(r"[A-Z_][A-Z0-9_]*", self.env_key)
            or self.env_key.startswith(("OPENAI_", "CODEX_"))
            or self.env_key == _NOAUTH_KEY
        ):
            raise ValueError("Use a dedicated route environment variable name")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> CodexRouteConfig:
        if not isinstance(value, dict):
            raise ValueError("Route settings must be an object")  # noqa: TRY004 - settings validation contract
        allowed = {"mode", "base_url", "model", "env_key", "allow_paid"}
        if set(value) - allowed:
            raise ValueError("Unknown route setting")
        if any(
            not isinstance(v, str)
            and not (k == "env_key" and v is None)
            and not (k == "allow_paid" and type(v) is bool)
               for k, v in value.items()):
            raise ValueError("Route settings must be strings")
        result = cls(**value)  # type: ignore[arg-type]
        result.validate()
        return result


class OmniRouteCodexDriver(CodexDriver):
    def __init__(self, *, route: CodexRouteConfig, **kwargs: Any) -> None:
        route.validate()
        if route.mode != "omniroute":
            raise ValueError("OmniRoute driver requires omniroute mode")
        self.route = route
        self._private_home = tempfile.TemporaryDirectory(prefix="empy-route-home-")
        super().__init__(**kwargs)

    @property
    def display_name(self) -> str:
        return "Codex via OmniRoute"

    def inspect_installation(self, *, refresh: bool = False) -> CodexInstallation:
        if not refresh and self._installation is None:
            return CodexInstallation(
                availability="unavailable", executable=self.requested_executable,
                version=None, authenticated=False,
                message="Local gateway status has not been checked.",
                remediation="Refresh local gateway status before execution.",
            )
        return super().inspect_installation(refresh=refresh)

    def _runtime_environment(self, executable: str | Path | None = None) -> dict[str, str]:
        environment = super()._runtime_environment(executable)
        for name in tuple(environment):
            if name.upper().startswith(("OPENAI_", "CODEX_")) or name.upper().endswith("_PROXY"):
                environment.pop(name)
        environment["CODEX_HOME"] = self._private_home.name
        environment["NO_PROXY"] = "*"
        if self.route.env_key is None:
            environment[_NOAUTH_KEY] = "empy-local-no-auth"
        return environment

    def _models(self) -> set[str]:
        self.route.validate()
        url = urlsplit(self.route.base_url)
        headers = {}
        if self.route.env_key:
            key = os.environ.get(self.route.env_key)
            if not key:
                raise ValueError("Dedicated route credential is missing")
            headers["Authorization"] = "Bearer " + key
        connection = http.client.HTTPConnection(url.hostname or "127.0.0.1", url.port, timeout=8)
        try:
            connection.request("GET", "/v1/models", headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Local gateway /models check failed; redirects are refused")
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Gateway model list exceeded size limit")
            payload = json.loads(raw)
            return {item["id"] for item in payload["data"] if isinstance(item.get("id"), str)}
        finally:
            connection.close()

    def _inspect_candidate(self, executable: str) -> CodexInstallation:
        version = self._run_preflight([executable, "--version"])
        help_result = self._run_preflight([executable, "exec", "--help"])
        help_text = help_result.stdout + help_result.stderr
        required = ("--ignore-user-config", "--json", "--ephemeral", "--output-last-message")
        version_text = self._bounded_output(version.stdout or version.stderr).strip()
        message = "Codex CLI lacks required isolated execution capabilities."
        ready = False
        if version.returncode == 0 and version_text and help_result.returncode == 0 and all(
            flag in help_text for flag in required
        ):
            try:
                ready = self.route.model in self._models()
                message = ("Local gateway advertises the selected free/local model. Responses execution remains unverified."
                           if ready else "Selected free/local model is absent from the local gateway.")
            except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
                message = "Local gateway preflight failed; check its URL, model and dedicated credential."
        return CodexInstallation(
            availability="available" if ready else "unavailable", executable=executable,
            version=version_text or None, authenticated=ready, message=message,
            remediation=None if ready else "Check OmniRoute and refresh; ChatGPT login is not used.",
        )

    def build_command(self, request: DriverExecutionRequest, *, executable: str,
                      final_message_path: str | Path) -> list[str]:
        self.route.validate()
        command = super().build_command(replace(request, ignore_user_config=True),
                                        executable=executable, final_message_path=final_message_path)
        config: dict[str, object] = {
            "model_provider": "empy_omniroute", "model": self.route.model,
            "web_search": "disabled",
            "model_providers.empy_omniroute.name": "OmniRoute local",
            "model_providers.empy_omniroute.base_url": self.route.base_url,
            "model_providers.empy_omniroute.wire_api": "responses",
            "model_providers.empy_omniroute.requires_openai_auth": False,
            "model_providers.empy_omniroute.env_key": self.route.env_key or _NOAUTH_KEY,
            "model_providers.empy_omniroute.request_max_retries": 0,
            "model_providers.empy_omniroute.stream_max_retries": 0,
        }
        command.pop()
        for key, value in config.items():
            command.extend(["--config", f"{key}={json.dumps(value)}"])
        return command + ["-"]

    @staticmethod
    def map_error(stderr: str, return_code: int) -> tuple[CodexErrorCode, str]:
        lowered = stderr.lower()
        if any(term in lowered for term in (
            "not supported", "unsupported model", "model_not_found", "unknown model",
            "unsupported endpoint", "responses is not supported",
        )):
            return "process_failed", (
                "The selected free/local model or Responses endpoint is unsupported by the local gateway. "
                "Check gateway compatibility and explicitly choose an available free/local model."
            )
        if any(term in lowered for term in ("401", "unauthorized", "authentication", "invalid api key", "not logged in", "sign in")):
            return "authentication_required", (
                "The local gateway or its upstream rejected authentication. Check the dedicated route "
                "credential and gateway backend configuration; ChatGPT login is not used."
            )
        if any(term in lowered for term in ("429", "rate limit", "quota", "too many requests")):
            return "rate_limited", (
                "The selected free/local gateway backend reported a quota or rate limit. "
                "Wait for recovery or explicitly choose another allowed free/local model."
            )
        if "403" in lowered or "forbidden" in lowered:
            return "permission_denied", (
                "The local gateway backend refused access to the selected free/local model. "
                "Check its backend permissions and model availability."
            )
        return CodexDriver.map_error(stderr, return_code)

    def _scrub(self, text: str) -> str:
        names = [name for name in os.environ if name.upper().startswith(("OPENAI_", "CODEX_"))]
        if self.route.env_key:
            names.append(self.route.env_key)
        for secret in sorted({os.environ[n] for n in names if os.environ.get(n)}, key=len, reverse=True):
            text = text.replace(json.dumps(secret)[1:-1], "[REDACTED]")
            text = text.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(Bearer\s+)[^\s\"\\]+", r"\1[REDACTED]", text)

    def execute_streaming(self, request: DriverExecutionRequest, *, node_id: str,
                          artifact_dir: str | Path,
                          on_progress: ProgressCallback | None = None) -> CodexNodeExecution:
        self.inspect_installation(refresh=True)
        destination = Path(artifact_dir).expanduser().resolve()
        def progress(event: Any) -> None:
            if on_progress:
                on_progress(replace(event, message=self._scrub(event.message),
                                    raw=json.loads(self._scrub(json.dumps(event.raw)))))
        with tempfile.TemporaryDirectory(prefix="empy-route-raw-") as private:
            result = super().execute_streaming(request, node_id=node_id,
                                               artifact_dir=private, on_progress=progress)
            destination.mkdir(parents=True, exist_ok=True)
            for source in Path(private).iterdir():
                if source.is_file():
                    (destination / source.name).write_text(
                        self._scrub(source.read_text(encoding="utf-8")), encoding="utf-8")
            return replace(result, summary=self._scrub(result.summary),
                           thread_id=self._scrub(result.thread_id) if result.thread_id else None,
                           changed_files=tuple(self._scrub(p) for p in result.changed_files),
                           error_message=self._scrub(result.error_message) if result.error_message else None,
                           events_path=str(destination / "events.jsonl"),
                           stderr_path=str(destination / "stderr.log"),
                           final_message_path=str(destination / "final-message.md"),
                           command_path=str(destination / "command.json"))
