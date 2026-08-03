from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    task = payload["task"]
    output = {
        "status": "passed",
        "result": {
            "task_id": task["task_id"],
            "message": f"Completed {task['title']}",
            "handoff_count": len(payload.get("handoffs", {})),
        },
        "evidence": [{"type": "example", "value": "deterministic-pass-agent"}],
        "memory_updates": {"last_task": task["task_id"]},
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
