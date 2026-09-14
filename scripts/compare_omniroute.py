"""Bounded synthetic free/local coding probe. Never invokes the direct account."""
from __future__ import annotations

import argparse
import ast
import json
import time
from pathlib import Path

from empy_studio.core import DriverExecutionRequest, ProjectDescriptor
from empy_studio.drivers.omniroute import CodexRouteConfig, OmniRouteCodexDriver


def probe(url: str, model: str, evidence: Path) -> dict[str, object]:
    route = CodexRouteConfig(mode="omniroute", base_url=url, model=model)
    route.validate()
    evidence.mkdir(parents=True, exist_ok=False)
    fixture = evidence / "fixture"
    fixture.mkdir()
    target = fixture / "calc.py"
    target.write_text("def add(left, right):\n    return left - right\n", encoding="utf-8")
    driver = OmniRouteCodexDriver(route=route, artifact_root=evidence / "runs")
    request = DriverExecutionRequest(
        project=ProjectDescriptor(root=fixture, project_type="python", display_name="Synthetic addition fixture"),
        task_id="free-route-comparison",
        prompt="Fix calc.py so add(left, right) returns left + right. Change only that return expression. No dependencies, network or other files. Finish briefly.",
        allowed_paths=("calc.py",), timeout_seconds=45, fresh_token_limit=12000,
        reasoning_effort="low", ignore_user_config=True,
    )
    started = time.monotonic()
    result = driver.execute_streaming(request, node_id="fixture-fix", artifact_dir=evidence / "run")
    try:
        verified = ast.dump(ast.parse(target.read_text())) == ast.dump(ast.parse("def add(left, right):\n    return left + right\n"))
    except SyntaxError:
        verified = False
    report = {
        "route": route.to_dict(), "status": result.status, "error_code": result.error_code,
        "error": result.error_message, "seconds": round(time.monotonic() - started, 2),
        "fixture_verified": verified, "usage": result.usage.to_dict() if result.usage else None,
        "billed_cost": None, "paid_routes_allowed": False,
        "note": "Synthetic fixture checked by AST without running generated code. Unknown usage/cost is not zero. Gateway must have no paid remapping/fallback.",
    }
    (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:20129/v1")
    parser.add_argument("--model", default="oc/north-mini-code-free")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.base_url, args.model, args.evidence_dir.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["fixture_verified"] and result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
