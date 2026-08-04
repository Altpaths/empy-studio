from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from empy_studio.core.project_service import ProjectDetection
from empy_studio.verification_pipeline import VerificationEvent, VerificationReport, VerificationRuntime

from .verification_workspace_adapter import VerificationWorkspaceAdapter


@dataclass(frozen=True)
class VerificationControllerFailure:
    message: str


VerificationControllerMessage = VerificationEvent | VerificationReport | VerificationControllerFailure


class VerificationController:
    def __init__(self, runtime: VerificationRuntime, store: VerificationWorkspaceAdapter) -> None:
        self.runtime = runtime
        self.store = store
        self._messages: queue.Queue[VerificationControllerMessage] = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, detection: ProjectDetection) -> None:
        if self.running:
            raise RuntimeError("verification is already running")

        def worker() -> None:
            try:
                report = self.runtime.run(
                    detection=detection,
                    evidence_root=self.store.evidence_root,
                    on_event=self._messages.put,
                )
                self.store.save(report)
                self._messages.put(report)
            except Exception as exc:  # noqa: BLE001
                self._messages.put(VerificationControllerFailure(str(exc)))

        self._thread = threading.Thread(target=worker, name="empy-verification", daemon=True)
        self._thread.start()

    def drain(self) -> tuple[VerificationControllerMessage, ...]:
        values: list[VerificationControllerMessage] = []
        while True:
            try:
                values.append(self._messages.get_nowait())
            except queue.Empty:
                return tuple(values)
