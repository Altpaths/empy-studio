from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .agent_contracts import AgentInput, AgentOutput

LocalHandler = Callable[[AgentInput], AgentOutput]


class AgentAdapter(Protocol):
    def execute(self, payload: AgentInput, timeout_seconds: float) -> AgentOutput:
        ...


class LocalAdapter:
    def __init__(self, handler: LocalHandler) -> None:
        self.handler = handler

    def execute(self, payload: AgentInput, timeout_seconds: float) -> AgentOutput:
        # Local handlers are deterministic integration/test adapters. Hard process
        # timeouts are provided by CommandAdapter.
        del timeout_seconds
        return self.handler(payload)


class CommandAdapter:
    def __init__(self, command: list[str]) -> None:
        if not command:
            raise ValueError("Command adapter requires a command")
        self.command = command

    def execute(self, payload: AgentInput, timeout_seconds: float) -> AgentOutput:
        with tempfile.TemporaryDirectory(prefix="empy-agent-") as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text(
                json.dumps(payload.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            command = [
                part.replace("{input}", str(input_path)).replace("{output}", str(output_path))
                for part in self.command
            ]
            try:
                result = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return AgentOutput(
                    status="failed",
                    error=f"Agent timed out after {timeout_seconds} seconds",
                    evidence=[{"type": "timeout", "seconds": timeout_seconds, "stderr": str(exc)}],
                )
            if result.returncode != 0:
                return AgentOutput(
                    status="failed",
                    error=f"Agent command exited with code {result.returncode}",
                    evidence=[{
                        "type": "command",
                        "returncode": result.returncode,
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    }],
                )
            if not output_path.exists():
                return AgentOutput(
                    status="failed",
                    error="Agent command did not create the required output file",
                )
            try:
                data = json.loads(output_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Output must be a JSON object")
                return AgentOutput.from_dict(data)
            except (json.JSONDecodeError, ValueError) as exc:
                return AgentOutput(status="failed", error=f"Invalid agent output: {exc}")
