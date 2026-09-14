#!/usr/bin/env python3
"""Exercise a packaged Empy Studio macOS app through its browser UI.

The acceptance fixture uses a deterministic Codex CLI double.  It validates the
packaged application, UI, orchestration, verification, export, and persistence;
it deliberately does not claim to validate the live Codex service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MARKER = "Empy acceptance homepage"
SECOND_MARKER = "Empy acceptance second ticket"
COMPLETION_MARKER = "Empy acceptance complete"
UNCHANGED = b"Keep this deployed file exactly unchanged.\n"
TICKETS = (
    f"Update public_html/index.html to contain {MARKER} and {COMPLETION_MARKER}. Preserve all other files.",
    f"Add {SECOND_MARKER} to public_html/index.html. Keep {MARKER} and {COMPLETION_MARKER}. Preserve all other files.",
)
TICKET = TICKETS[0]


@dataclass
class Check:
    name: str
    status: str
    detail: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_fixture_zip(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    package = {
        "name": "holda-acceptance",
        "private": True,
        "scripts": {"test": "node verify.mjs"},
    }
    verifier = (
        "import fs from 'node:fs';\n"
        "const body = fs.readFileSync('public_html/index.html', 'utf8');\n"
        f"if (!body.includes({json.dumps(MARKER)})) {{\n"
        "  console.error('acceptance marker is missing'); process.exit(1);\n"
        "}\n"
        f"if (!body.includes({json.dumps(COMPLETION_MARKER)})) {{\n"
        "  console.error('completion marker is missing'); process.exit(2);\n"
        "}\n"
        "console.log('acceptance marker verified');\n"
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("holda-acceptance/package.json", json.dumps(package, indent=2) + "\n")
        archive.writestr("holda-acceptance/package-lock.json", json.dumps({"name": "holda-acceptance", "lockfileVersion": 3, "requires": True, "packages": {"": {"name": "holda-acceptance"}}}) + "\n")
        archive.writestr("holda-acceptance/verify.mjs", verifier)
        archive.writestr("holda-acceptance/public_html/unchanged.txt", UNCHANGED)
        archive.writestr(
            "holda-acceptance/public_html/index.html",
            "<!doctype html><html><body><main>Original fixture</main></body></html>\n",
        )
    return destination


def write_fake_codex(bin_dir: Path, scenario: str = "normal") -> Path:
    bin_dir = bin_dir.expanduser().resolve()
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "codex"
    target.write_text(
        f"#!{sys.executable}\n" + """
import json
import pathlib
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.0.0-acceptance")
    raise SystemExit(0)
if args[:2] == ["login", "status"]:
    print("Logged in (deterministic acceptance provider)")
    raise SystemExit(0)
if args[:2] == ["exec", "--help"] or args == ["exec", "--help"]:
    print("Usage: codex exec --json --cd PATH --output-last-message PATH")
    raise SystemExit(0)
if not args or args[0] != "exec":
    print("unsupported fake codex invocation", file=sys.stderr)
    raise SystemExit(2)

root = pathlib.Path(args[args.index("--cd") + 1])
final_path = pathlib.Path(args[args.index("--output-last-message") + 1])
_prompt = sys.stdin.read()
second = "Empy acceptance second ticket" in _prompt
counter = pathlib.Path(__file__).parent / ("ticket-2-count.txt" if second else "ticket-1-count.txt")
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
scenario = (pathlib.Path(__file__).parent / "scenario.txt").read_text()
body = "Empy acceptance homepage Empy acceptance complete"
if second:
    body += " Empy acceptance second ticket"
if scenario == "recovery" and count == 1:
    body = "Incomplete requested homepage"
elif scenario == "recovery" and count == 2:
    body = "Empy acceptance homepage"
changed = root / "public_html" / "index.html"
changed.parent.mkdir(parents=True, exist_ok=True)
changed.write_text(
    f"<!doctype html><html><body><main>{body}</main></body></html>\\n",
    encoding="utf-8",
)
final_path.parent.mkdir(parents=True, exist_ok=True)
final_path.write_text("Updated the requested homepage and preserved other files.\\n", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "acceptance-thread"}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {"type": "file_change", "status": "completed", "changes": [
        {"path": "public_html/index.html", "kind": "update"}
    ]},
}), flush=True)
time.sleep(1)
print(json.dumps({"type": "turn.completed"}), flush=True)
""",
        encoding="utf-8",
    )
    (bin_dir / "scenario.txt").write_text(scenario, encoding="utf-8")
    target.chmod(0o755)
    return target


def verify_export_archive(archive_path: Path, ticket: int = 1) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        # Exact project-relative names prevent public_html/public_html nesting,
        # duplicate ZIP entries, traversal, and overwriting unchanged files.
        if archive.namelist() != ["public_html/index.html"]:
            raise AssertionError("delta ZIP must contain only project-relative public_html/index.html")
        body = archive.read("public_html/index.html").decode("utf-8")
        required = [MARKER, COMPLETION_MARKER] + ([SECOND_MARKER] if ticket == 2 else [])
        if not all(marker in body for marker in required):
            raise AssertionError("exported homepage is missing requested acceptance markers")


def verify_export_sidecars(archive_path: Path, manifest_path: Path, checksum_path: Path) -> None:
    parts = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[0].lower() != sha256(archive_path):
        raise AssertionError("export checksum does not match the downloaded ZIP")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("archive_mode") != "delta" or manifest.get("extraction_root") != "."
            or manifest.get("changed_files") != ["public_html/index.html"] or manifest.get("deleted_files") != []):
        raise AssertionError("export manifest has unexpected delta paths, deletions, or extraction root")
    with zipfile.ZipFile(archive_path) as archive:
        actual = [{"path": name, "size": len(archive.read(name)),
                   "sha256": hashlib.sha256(archive.read(name)).hexdigest()} for name in archive.namelist()]
    if manifest.get("files") != actual or manifest.get("file_count") != len(actual):
        raise AssertionError("export manifest file hashes/sizes do not match ZIP")


def verify_deployment(fixture: Path, archive_path: Path, destination: Path) -> None:
    destination.mkdir()
    with zipfile.ZipFile(fixture) as archive:
        for name in archive.namelist():
            relative = PurePosixPath(name).relative_to("holda-acceptance")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    unchanged = {path.relative_to(destination): (sha256(path), path.stat().st_mtime_ns)
                 for path in destination.rglob("*") if path.is_file() and path.name != "index.html"}
    verify_export_archive(archive_path, ticket=2)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(destination)  # Names were checked exactly above.
    for relative, expected in unchanged.items():
        path = destination / relative
        if (sha256(path), path.stat().st_mtime_ns) != expected:
            raise AssertionError(f"deployment changed untouched baseline file: {relative}")
    if (destination / "public_html/public_html").exists():
        raise AssertionError("deployment duplicated public_html nesting")


def assert_verification(state: dict[str, Any]) -> None:
    report = state.get("verification") or {}
    results = report.get("results") or []
    if (state.get("run_status") != "completed" or report.get("status") != "pass"
            or not report.get("finalized_at") or not results or report.get("diagnostics")):
        raise AssertionError("run must have successful, finalized, nonempty verification evidence")
    if any(result.get("status") != "pass" or result.get("returncode") != 0 for result in results):
        raise AssertionError("a real verification check failed")
    if not any("acceptance marker verified" in str(result.get("stdout", "")) for result in results):
        raise AssertionError("fixture Node verifier did not run successfully")


def result_identity(state: dict[str, Any]) -> dict[str, Any]:
    """Stable persisted identities/results, not just a nonempty projects list."""
    assert_verification(state)
    project = state.get("active_project") or {}
    report = state.get("run_report") or {}
    review = state.get("review") or {}
    exported = state.get("export") or {}
    if (not project.get("id") or not state.get("active_task_id") or not report.get("run_id")
            or not exported.get("sha256") or not review.get("accepted_count") or review.get("pending_count")):
        raise AssertionError("accepted task/run/export identity is incomplete")
    return {"project_id": project["id"], "task_id": state["active_task_id"], "task": state["task"],
            "run_id": report["run_id"], "verification": state["verification"],
            "review": review, "export": exported}


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def fetch_json(url: str, token: str, timeout: float = 5) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"X-Empy-Token": token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def fetch_file(url: str, token: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"X-Empy-Token": token})
    with urllib.request.urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


def wait_for_server(base_url: str, token: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Empy app exited before becoming healthy ({process.returncode})")
        try:
            fetch_json(f"{base_url}/api/health", token)
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.25)
    raise TimeoutError("Empy app did not become healthy within 45 seconds")


def launch_app(
    executable: Path, workspace: Path, port: int, token: str, fake_bin: Path, log_path: Path
) -> tuple[subprocess.Popen[str], Any]:
    log = log_path.open("a", encoding="utf-8")
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}"
    process = subprocess.Popen(
        [
            str(executable),
            "--workspace",
            str(workspace),
            "--port",
            str(port),
            "--token",
            token,
            "--no-open",
        ],
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log


def stop_app(process: subprocess.Popen[str] | None, log: Any | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log is not None:
        log.close()


def capture(page: Any, evidence_dir: Path, name: str, base_url: str, token: str) -> None:
    page.screenshot(path=str(evidence_dir / f"{name}.png"), full_page=True)
    state = fetch_json(f"{base_url}/api/state", token)
    (evidence_dir / f"{name}-state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_once(
    executable: Path, root: Path, iteration: int, scenario: str = "normal",
    browser_executable: Path | None = None,
) -> list[Check]:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    evidence = root / f"run-{iteration:02d}"
    evidence.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture_zip(evidence / "holda-acceptance.zip")
    fake_bin = evidence / "fake-bin"
    write_fake_codex(fake_bin, scenario)
    workspace = evidence / "workspace"
    log_path = evidence / "empy-app.log"
    token = hashlib.sha256(f"empy-acceptance-{iteration}".encode()).hexdigest()
    checks: list[Check] = []
    process: subprocess.Popen[str] | None = None
    log: Any | None = None
    browser = None
    context = None
    try:
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        process, log = launch_app(executable, workspace, port, token, fake_bin, log_path)
        wait_for_server(base_url, token, process)
        checks.append(Check("app_launch", "pass", "Packaged app served a healthy local API."))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                **({"executable_path": str(browser_executable)} if browser_executable else {})
            )
            context = browser.new_context(**({"record_video_dir": str(evidence / "video")} if browser_executable is None else {}))
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            def console_message(message: Any) -> None:
                with (evidence / "browser-console.log").open("a", encoding="utf-8") as stream:
                    stream.write(f"{message.type}: {message.text}\n")

            page.on("console", console_message)
            try:
                page.goto(f"{base_url}/?token={token}", wait_until="networkidle")
                page.get_by_role("button", name="Switch language").click()
                page.get_by_role("button", name="Choose ZIP").first.click()
                page.locator("#zip-upload").set_input_files(str(fixture))
                page.get_by_role("heading", name="New ticket").wait_for(timeout=30_000)
                capture(page, evidence, "01-imported", base_url, token)

                identities = []
                for ticket_number, ticket_text in enumerate(TICKETS, 1):
                    if ticket_number > 1:
                        page.locator('[data-action="new-ticket"]').click()
                        page.get_by_role("heading", name="New ticket").wait_for(timeout=30_000)
                    assert page.locator("#budget-preset").count() == 0
                    page.locator("#tasks").fill(ticket_text)
                    page.get_by_role("button", name="Analyze and build plan").click()
                    page.get_by_role("heading", name="Plan is ready").wait_for(timeout=30_000)
                    planned = fetch_json(f"{base_url}/api/state", token)
                    if ticket_number == 1:
                        task_id = planned["active_task_id"]
                        page.locator('[data-action="go-task"]').click()
                        if page.locator("#tasks").input_value() != ticket_text:
                            raise AssertionError("editing must preserve the same ticket draft")
                        page.get_by_role("button", name="Analyze and build plan").click()
                        page.get_by_role("heading", name="Plan is ready").wait_for(timeout=30_000)
                        if fetch_json(f"{base_url}/api/state", token)["active_task_id"] != task_id:
                            raise AssertionError("editing a draft must not create a duplicate ticket")
                    assert page.locator("#recovery-tokens").count() == 0
                    assert planned["budget"]["preset"] == "economy"
                    page.locator("#recovery-attempts").fill("3")
                    page.locator('[data-action="save-recovery-policy"]').click()
                    page.get_by_role("heading", name="Plan is ready").wait_for(timeout=30_000)
                    capture(page, evidence, f"ticket-{ticket_number}-02-plan", base_url, token)

                    page.get_by_role("button", name="Start run").click()
                    deadline = time.monotonic() + 180
                    while True:
                        outcome = fetch_json(f"{base_url}/api/state", token)
                        verified = outcome.get("verification") or {}
                        if (not outcome.get("running") and outcome.get("run_status") == "completed"
                                and verified.get("status") == "pass" and verified.get("finalized_at")):
                            break
                        stopped = (outcome.get("recovery") or {}).get("stop_reason")
                        if stopped and not outcome.get("running"):
                            raise AssertionError(f"Workflow stopped: {stopped}; {outcome.get('error')}")
                        if time.monotonic() > deadline:
                            raise AssertionError(f"Timed out waiting for finalized verification: {outcome.get('error')}")
                        time.sleep(0.2)
                    page.get_by_role("heading", name="Result and review").wait_for(timeout=30_000)
                    capture(page, evidence, f"ticket-{ticket_number}-03-review", base_url, token)
                    assert_verification(fetch_json(f"{base_url}/api/state", token))
                    selector = '[data-action="decide-file"][data-decision="accept"][data-relative-path="public_html/index.html"]' if ticket_number == 1 else '[data-action="decide"][data-decision="accept"]'
                    page.locator(selector).click()
                    page.get_by_role("button", name="Export project ZIP").wait_for(state="visible", timeout=30_000)
                    page.get_by_role("button", name="Export project ZIP").click()
                    page.get_by_role("heading", name="Export is ready").wait_for(timeout=30_000)
                    capture(page, evidence, f"ticket-{ticket_number}-04-export", base_url, token)

                    state = fetch_json(f"{base_url}/api/state", token)
                    export = state.get("export") or {}
                    urls = export.get("downloads") or {}
                    archive_url = urls.get("archive") or "/api/export/download"
                    manifest_url = urls.get("manifest") or "/api/export/manifest"
                    checksum_url = urls.get("checksum") or "/api/export/checksum"
                    exported_zip = evidence / f"ticket-{ticket_number}-exported-project.zip"
                    fetch_file(f"{base_url}{archive_url}", token, exported_zip)
                    manifest_path = evidence / f"ticket-{ticket_number}-export-manifest.json"
                    checksum_path = evidence / f"ticket-{ticket_number}-export-checksum.txt"
                    fetch_file(f"{base_url}{manifest_url}", token, manifest_path)
                    fetch_file(f"{base_url}{checksum_url}", token, checksum_path)
                    verify_export_archive(exported_zip, ticket_number)
                    verify_export_sidecars(exported_zip, manifest_path, checksum_path)
                    checks.append(Check("browser_workflow", "pass", "Import through export completed in the UI."))
                    checks.append(Check("export_integrity", "pass", f"ZIP verified: sha256={sha256(exported_zip)}"))

                    identities.append(result_identity(state))
                    if scenario == "recovery":
                        count = int((fake_bin / f"ticket-{ticket_number}-count.txt").read_text())
                        if count != 3 or (state.get("recovery") or {}).get("status") != "verified":
                            raise AssertionError("recovery must pass after exactly two automatic corrections")
                        checks.append(Check(f"ticket_{ticket_number}_recovery", "pass", "Two distinct verifier failures corrected automatically."))
                if identities[0]["task_id"] == identities[1]["task_id"]:
                    raise AssertionError("sequential tickets must have distinct persisted task IDs")
                expected_identity = identities[-1]
                verify_deployment(fixture, exported_zip, evidence / "deployed")
            except Exception:
                (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                try:
                    capture(page, evidence, "failure", base_url, token)
                except Exception as capture_error:  # noqa: BLE001 - preserve the original failure and record cleanup evidence
                    (evidence / "capture-error.txt").write_text(str(capture_error), encoding="utf-8")
                raise
            finally:
                try:
                    context.tracing.stop(path=str(evidence / "playwright-trace.zip"))
                finally:
                    context.close()
                    context = None
                    browser.close()
                    browser = None

        stop_app(process, log)
        process, log = None, None

        restart_port = free_port()
        restart_url = f"http://127.0.0.1:{restart_port}"
        process, log = launch_app(executable, workspace, restart_port, token, fake_bin, log_path)
        wait_for_server(restart_url, token, process)
        restarted = fetch_json(f"{restart_url}/api/state", token)
        (evidence / "05-restart-state.json").write_text(
            json.dumps(restarted, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if result_identity(restarted) != expected_identity:
            raise AssertionError("restart changed the accepted project/task/run/verification/review/export")
        tasks = restarted.get("tasks") or []
        if not {item["task_id"] for item in identities}.issubset({item["id"] for item in tasks}):
            raise AssertionError("restart lost one of the two sequential tickets")
        checks.append(Check("restart_persistence", "pass", "Exact accepted project, task, run, verification, review and export retained; both tickets present."))
        return checks
    except Exception as error:
        checks.append(Check("acceptance", "fail", f"{type(error).__name__}: {error}"))
        raise
    finally:
        if context is not None:
            try:
                context.tracing.stop(path=str(evidence / "playwright-trace.zip"))
                context.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve the primary acceptance error
                (evidence / "cleanup-errors.log").open("a", encoding="utf-8").write(
                    f"context cleanup: {cleanup_error}\n"
                )
        if browser is not None:
            try:
                browser.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve the primary acceptance error
                (evidence / "cleanup-errors.log").open("a", encoding="utf-8").write(
                    f"browser cleanup: {cleanup_error}\n"
                )
        stop_app(process, log)
        (evidence / "checks.json").write_text(
            json.dumps([asdict(item) for item in checks], indent=2), encoding="utf-8"
        )


def write_report(destination: Path, tag: str, runs: list[dict[str, Any]]) -> None:
    passed = all(run["status"] == "pass" for run in runs)
    lines = [
        "# Empy Studio macOS Acceptance Report",
        "",
        f"- Release: `{tag}`",
        f"- Overall result: **{'PASS' if passed else 'FAIL'}**",
        "- Provider scope: deterministic local Codex test double; live Codex service was not tested.",
        "- Product scope: downloaded app, browser UI, orchestration, verification, export, and restart persistence.",
        "",
        "## Runs",
        "",
    ]
    for run in runs:
        lines.append(f"- Run {run['iteration']}: **{run['status'].upper()}** — {run['detail']}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True, help="Path to Empy Studio.app")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--release-tag", default="unknown")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--scenario", choices=("normal", "recovery"), default="normal")
    parser.add_argument("--browser-executable", type=Path, help="Use an installed Chrome executable in a new isolated browser context")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.app = args.app.expanduser().resolve()
    args.evidence_dir = args.evidence_dir.expanduser().resolve()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be at least 1")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    executable = args.app / "Contents" / "MacOS" / "Empy Studio"
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"app executable is missing or not executable: {executable}")
        with (args.app / "Contents" / "Info.plist").open("rb") as stream:
            metadata = plistlib.load(stream)
        expected_version = args.release_tag.removeprefix("v")
        if args.release_tag != "unknown" and any(
            metadata.get(key) != expected_version
            for key in ("CFBundleVersion", "CFBundleShortVersionString")
        ):
            raise ValueError("App bundle version does not match the requested release tag")
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        failures = [{"iteration": 0, "status": "fail", "detail": str(error)}]
        (args.evidence_dir / "acceptance-results.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
        write_report(args.evidence_dir / "ACCEPTANCE_REPORT.md", args.release_tag, failures)
        return 1
    runs: list[dict[str, Any]] = []
    exit_code = 0
    for iteration in range(1, args.repetitions + 1):
        try:
            checks = run_once(executable, args.evidence_dir, iteration, args.scenario, args.browser_executable)
            runs.append({"iteration": iteration, "status": "pass", "detail": f"{len(checks)} checks passed"})
        except Exception as error:  # noqa: BLE001 - every run must be recorded and later runs must continue
            exit_code = 1
            runs.append({"iteration": iteration, "status": "fail", "detail": f"{type(error).__name__}: {error}"})
    (args.evidence_dir / "acceptance-results.json").write_text(
        json.dumps(runs, indent=2), encoding="utf-8"
    )
    write_report(args.evidence_dir / "ACCEPTANCE_REPORT.md", args.release_tag, runs)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
