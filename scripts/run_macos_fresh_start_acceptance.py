#!/usr/bin/env python3
"""Check an extracted app with isolated HOME and no explicit workspace override."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

from empy_studio.web_desktop import GuidedState
from scripts.run_macos_app_acceptance import (
    fetch_json,
    free_port,
    stop_app,
    wait_for_server,
    write_fake_codex,
)


def check(app: Path, evidence: Path) -> dict[str, object]:
    evidence.mkdir(parents=True, exist_ok=False)
    home = evidence / "home"
    legacy = home / "Library/Application Support/Empy Studio"
    fixture = evidence / "user-project"
    fixture.mkdir()
    (fixture / "README.md").write_text("User project\n", encoding="utf-8")
    old = GuidedState(legacy)
    old.import_path(str(fixture))
    old.create_plan("Update README")
    legacy_digest = hashlib.sha256((legacy / "workspace.sqlite3").read_bytes()).hexdigest()
    fake_bin = evidence / "fake-bin"
    fake_bin.mkdir()
    write_fake_codex(fake_bin, "normal")
    environment = dict(os.environ, HOME=str(home), PATH=f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    checks: list[str] = []

    def launch(target: Path):
        port = free_port()
        token = "isolated-fresh-start-acceptance"
        log = (evidence / "app.log").open("a", encoding="utf-8")
        process = subprocess.Popen([str(target / "Contents/MacOS/Empy Studio"), "--port", str(port), "--token", token, "--no-open"], env=environment, stdout=log, stderr=subprocess.STDOUT, text=True)
        url = f"http://127.0.0.1:{port}"
        try:
            wait_for_server(url, token, process)
        except BaseException:
            stop_app(process, log)
            raise
        return process, log, url, token

    def post(url: str, token: str, path: str, body: dict[str, object]):
        request = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"X-Empy-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def assert_empty(state):
        assert state["phase"] == "project"
        assert state["projects"] == []
        assert state["active_project"] is None
        assert state["active_task_id"] is None
        assert state["verification"] is None
        assert state["running"] is False

    process, log, url, token = launch(app)
    try:
        assert_empty(fetch_json(url + "/api/state", token))
        checks.append("fresh default launch ignores legacy project and test history")
        post(url, token, "/api/import", {"path": str(fixture)})
        planned = post(url, token, "/api/plan", {"tasks": "Update README", "budget_preset": "extended"})
        assert planned["budget"]["preset"] == "economy"
        task_id = planned["active_task_id"]
        project_id = planned["active_project"]["id"]
        checks.append("older client cannot select extended budget")
    finally:
        stop_app(process, log)
    process, log, url, token = launch(app)
    try:
        state = fetch_json(url + "/api/state", token)
        assert state["phase"] == "project"
        assert state["active_task_id"] is None
        assert len(state["projects"]) == 1
        assert state["projects"][0]["id"] == project_id
        assert state["projects"][0]["tasks"][0]["id"] == task_id
        checks.append("relaunch starts at first page and keeps user ticket for follow-up")
    finally:
        stop_app(process, log)
    copied_app = evidence / "new-download/Empy Studio.app"
    copied_app.parent.mkdir()
    subprocess.run(["ditto", "--norsrc", str(app), str(copied_app)], check=True)
    process, log, url, token = launch(copied_app)
    try:
        assert_empty(fetch_json(url + "/api/state", token))
        checks.append("new app copy starts empty under same HOME")
    finally:
        stop_app(process, log)
    assert hashlib.sha256((legacy / "workspace.sqlite3").read_bytes()).hexdigest() == legacy_digest
    checks.append("legacy database remains byte-identical")
    return {"status": "passed", "checks": checks, "live_provider": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    try:
        report = check(args.app.resolve(), evidence)
    except Exception as exc:
        report = {"status": "failed", "error": str(exc)}
        raise
    finally:
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
