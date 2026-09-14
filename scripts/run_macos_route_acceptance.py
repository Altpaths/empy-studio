"""Exercise the packaged route UI against a local catalog mock, with no model calls."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


def check(app: Path, evidence: Path, browser: str) -> dict[str, object]:
    evidence.mkdir(parents=True, exist_ok=False)
    catalog = {'status': 200, 'requests': 0}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            catalog['requests'] += 1
            assert self.path == '/v1/models'
            self.send_response(catalog['status'])
            self.end_headers()
            self.wfile.write(json.dumps({'data': [{'id': 'oc/big-pickle'}]}).encode())
        def do_POST(self):
            raise AssertionError('No model inference is allowed in this UI test')
        def log_message(self, *args):
            pass
    gateway = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=gateway.serve_forever, daemon=True)
    worker.start()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    token = 'isolated-route-ui-acceptance'
    url = f'http://127.0.0.1:{port}'
    def state():
        request = urllib.request.Request(url + '/api/state', headers={'X-Empy-Token': token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    log = (evidence / 'app.log').open('w')
    process = subprocess.Popen([str(app / 'Contents/MacOS/Empy Studio'), '--workspace', str(evidence / 'workspace'), '--start-page', '--no-open', '--port', str(port), '--token', token], stdout=log, stderr=log, env=os.environ.copy())
    checks = []
    try:
        for _ in range(100):
            try:
                initial = state()
                break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('Packaged app did not start')
        assert initial['phase'] == 'project' and initial['projects'] == []
        checks.append('fresh project screen with no saved history')
        with sync_playwright() as playwright:
            chrome = playwright.chromium.launch(executable_path=browser, headless=True)
            page = chrome.new_page()
            page.goto(url + '/?token=' + token)
            page.locator('.model-route summary').click()
            page.locator('#model-route-mode').select_option('omniroute')
            page.locator('#model-route-url').fill(f'http://127.0.0.1:{gateway.server_port}/v1')
            page.locator('#model-route-model').fill('oc/big-pickle')
            page.locator('[data-action="save-model-route"]').click()
            page.wait_for_function("document.querySelector('#model-route-mode')?.value === 'omniroute'")
            assert state()['model_route']['model'] == 'oc/big-pickle'
            assert catalog['requests'] == 0
            page.locator('[data-action="refresh-engine"]').click()
            page.wait_for_function("document.querySelector('.engine .status-pill')?.classList.contains('completed')")
            assert state()['engine']['ready']
            count = catalog['requests']
            for _ in range(5):
                assert state()['model_route']['mode'] == 'omniroute'
            assert catalog['requests'] == count
            checks.append('explicit route saved; cached polling does not rescan gateway')
            page.locator('.model-route summary').click()
            page.locator('#model-route-model').fill('auto')
            page.locator('[data-action="save-model-route"]').click()
            page.wait_for_function(
                "document.querySelector('#model-route-model')?.value === 'oc/big-pickle'"
            )
            assert state()['model_route']['model'] == 'oc/big-pickle'
            checks.append('automatic/paid model rejection preserves prior route')
            catalog['status'] = 503
            page.locator('[data-action="refresh-engine"]').click()
            page.wait_for_function("document.querySelector('.engine .status-pill')?.classList.contains('failed')")
            assert not state()['engine']['ready']
            assert state()['model_route']['mode'] == 'omniroute'
            checks.append('gateway failure never switches to Direct')
            page.screenshot(path=str(evidence / 'route-ui.png'), full_page=True)
            chrome.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        gateway.shutdown()
        gateway.server_close()
        worker.join()
    return {'status': 'passed', 'checks': checks, 'gateway': 'mock catalog', 'model_calls': 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--browser', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    args = parser.parse_args()
    report = check(args.app.resolve(), args.evidence_dir.resolve(), args.browser)
    (args.evidence_dir / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
