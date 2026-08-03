from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AgentMemoryStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, agent_id: str) -> Path:
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in agent_id)
        return self.root / f"{safe}.json"

    def load(self, agent_id: str) -> dict[str, Any]:
        path = self._path(agent_id)
        if not path.exists():
            return {"agent_id": agent_id, "revision": 0, "data": {}, "history": []}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Invalid memory file for agent {agent_id}")
        return value

    def update(
        self,
        agent_id: str,
        updates: dict[str, Any],
        *,
        run_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        memory = self.load(agent_id)
        data = dict(memory.get("data", {}))
        data.update(updates)
        history = list(memory.get("history", []))
        history.append({
            "run_id": run_id,
            "task_id": task_id,
            "updates": updates,
        })
        memory = {
            "agent_id": agent_id,
            "revision": int(memory.get("revision", 0)) + 1,
            "data": data,
            "history": history[-100:],
        }
        path = self._path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return memory
