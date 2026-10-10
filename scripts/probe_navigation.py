"""Opt-in hosted-model navigation probe on invented, randomized sites. Never packaged."""
import asyncio
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit
import uuid

import httpx
from playwright.async_api import async_playwright

from hackathon_toolkit.rfq.browser import BrowserSession
from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.runtime import Agent, BrowserWorker, ModelClient, agent_loop, save_artifacts
from hackathon_toolkit.rfq.trace import Trace


async def main():
    artifacts = Path('.rfq-artifacts/navigation-probe') / uuid.uuid4().hex[:8]
    artifacts.mkdir(parents=True, exist_ok=True)
    print(json.dumps({'probe_artifacts': str(artifacts)}), flush=True)
    processes = []
    outcomes = []
    with tempfile.TemporaryDirectory(prefix='rfq-nav-probe-') as directory:
        try:
            endpoints = []
            for index in range(4):
                profile = Path(directory) / str(index)
                processes.append(subprocess.Popen([shutil.which('google-chrome'), '--headless=new', '--no-sandbox',
                    '--disable-dev-shm-usage', '--no-first-run', '--remote-debugging-port=0',
                    f'--user-data-dir={profile}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                for _ in range(100):
                    if (profile / 'DevToolsActivePort').exists():
                        break
                    await asyncio.sleep(.05)
                port = (profile / 'DevToolsActivePort').read_text().splitlines()[0]
                endpoints.append(f'http://127.0.0.1:{port}')
            async with async_playwright() as playwright, httpx.AsyncClient() as client:
                roots = [f'https://probe-{i}.test/' for i in range(4)]
                book = EvidenceBook()
                browser = await BrowserSession.connect(playwright, endpoints, book, roots)
                run = {'brief': 'Synthetic navigation check, no real RFQ or submission. Find the requested stock record.',
                       'access': [{'url': root} for root in roots], 'submission': {'url': roots[0]}, 'answer_schema': {}}
                parent = Agent(browser, book, run)
                parent.trace = Trace(artifacts, [])
                model = ModelClient(client, os.environ.get('QWEN_BASE_URL', 'http://127.0.0.1:8765/qwen/v1'),
                                    os.environ.get('QWEN_API_KEY', 'local'))
                for index, root in enumerate(roots):
                    # Every route and fact changes between executions. The model sees only roots and its search task.
                    search_path = '/' + uuid.uuid4().hex
                    result_path = '/' + uuid.uuid4().hex
                    product = 'FIXTURE-' + uuid.uuid4().hex[:6]
                    stock = random.randint(11, 99)
                    inventory = f'<a href="{search_path}">Materialsuche / Inventory search</a>'
                    if index % 2:
                        inventory = '<button onclick="document.querySelector(\'nav\').hidden=false">Lagerverwaltung</button><nav hidden>' + inventory + '</nav>'
                    home = '<h1>Operations</h1><button>Help</button>' + inventory
                    if index >= 2:
                        home += '<dialog open><p>Optional survey</p><button onclick="this.closest(\'dialog\').remove()">Dismiss survey</button></dialog>'
                    search = f'<h1>Material search</h1><form action="{result_path}"><label>Component code <input name="q"></label><button>Search records</button></form>'

                    async def route_handler(route, request, *, home=home, search=search, search_path=search_path,
                                            result_path=result_path, product=product, stock=stock):
                        url = urlsplit(route.request.url)
                        if url.path == '/':
                            body = home
                        elif url.path == search_path:
                            body = search
                        elif url.path == result_path and parse_qs(url.query).get('q') == [product]:
                            body = f'<h1>Selected result</h1><table><tr><th>Component</th><th>Stock pieces</th></tr><tr><td>{product}</td><td>{stock}</td></tr></table>'
                        else:
                            body = '<h1>No matching record</h1>'
                        await route.fulfill(content_type='text/html', body=body)

                    await browser.browsers[index].contexts[0].route(root + '**', route_handler)
                    worker = BrowserWorker(parent, index, f'Open {root}, discover the inventory search, search component {product}, '
                        'extract the selected result table, cite the row including stock, and report. Do not guess paths. Ignore unrelated controls.')
                    failure = None
                    try:
                        await agent_loop(worker, model, seconds=150, max_steps=25)
                    except (TimeoutError, RuntimeError) as exc:
                        failure = type(exc).__name__
                    facts = [f for f in book.facts.values() if product in f['quote'] and str(stock) in f['quote']]
                    outcome = {'browser': index, 'layout': index % 2, 'modal': index >= 2,
                               'reported': worker.done, 'cited_correct_record': bool(facts), 'error': failure}
                    outcomes.append(outcome)
                    print(json.dumps({'navigation_probe': outcome}), flush=True)
                    save_artifacts(artifacts, parent, [])
                    (artifacts / 'outcomes.json').write_text(json.dumps(outcomes, indent=2))
        finally:
            for process in processes:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
    if not all(item['reported'] and item['cited_correct_record'] for item in outcomes):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
