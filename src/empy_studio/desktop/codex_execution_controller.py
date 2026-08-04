from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from empy_studio.core import (
    AgentRunGraph,
    ContextSelection,
    ProjectDescriptor,
    TokenBudget,
)
from empy_studio.drivers import (
    CodexGraphExecution,
    CodexGraphRuntime,
    CodexProgressEvent,
)

from .codex_execution_workspace_adapter import CodexExecutionWorkspaceAdapter


@dataclass(frozen=True)
class CodexControllerFailure:
    message: str


CodexControllerMessage = (
    CodexProgressEvent | CodexGraphExecution | CodexControllerFailure
)


class CodexExecutionController:
    """Run Codex outside Tk's main thread and expose a polling queue."""

    def __init__(
        self,
        *,
        runtime: CodexGraphRuntime,
        store: CodexExecutionWorkspaceAdapter,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self._messages: queue.Queue[CodexControllerMessage] = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        *,
        graph: AgentRunGraph,
        selection: ContextSelection,
        budget: TokenBudget,
        project: ProjectDescriptor,
    ) -> None:
        if self.running:
            raise RuntimeError("a Codex execution is already running")

        def worker() -> None:
            try:
                result = self.runtime.run(
                    graph=graph,
                    selection=selection,
                    budget=budget,
                    project=project,
                    on_progress=self._messages.put,
                )
                self.store.save_run(result)
                self._messages.put(result)
            except Exception as exc:  # noqa: BLE001
                self._messages.put(
                    CodexControllerFailure(
                        message=f"Unable to execute Codex run: {exc}",
                    )
                )

        self._thread = threading.Thread(
            target=worker,
            name="empy-codex-execution",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self.runtime.cancel()

    def drain(self) -> tuple[CodexControllerMessage, ...]:
        values: list[CodexControllerMessage] = []
        while True:
            try:
                values.append(self._messages.get_nowait())
            except queue.Empty:
                return tuple(values)
