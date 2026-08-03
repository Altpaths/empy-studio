from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


def run_command(item: dict[str, Any], cwd: str | None = None) -> dict[str, Any]:
    result = subprocess.run(item["command"], cwd=cwd, text=True, capture_output=True, shell=True)
    return {
        "id": item["id"],
        "type": "command",
        "status": "pass" if result.returncode == 0 else "fail",
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def check_file(item: dict[str, Any]) -> dict[str, Any]:
    path = Path(item["path"])
    exists = path.exists()
    result: dict[str, Any] = {
        "id": item["id"], "type": "file", "status": "pass" if exists else "fail", "exists": exists
    }
    if exists and path.is_file():
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify(manifest: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    cwd = manifest.get("cwd")
    for item in manifest.get("checks", []):
        kind = item["type"]
        if kind == "command":
            results.append(run_command(item, cwd))
        elif kind == "file":
            results.append(check_file(item))
        elif kind == "external":
            results.append({
                "id": item["id"], "type": "external", "status": "pending",
                "reason": item.get("reason", "External environment access required"),
            })
        else:
            results.append({"id": item.get("id", "unknown"), "type": kind, "status": "fail", "reason": "Unknown check type"})

    failed = [result["id"] for result in results if result["status"] == "fail"]
    pending = [result["id"] for result in results if result["status"] == "pending"]
    status = "pass" if not failed and not pending else ("fail" if failed else "release_candidate")
    return {"engine": "empy_studio.verifier", "results": results, "failed": failed, "pending": pending, "status": status}
