"""Paired, synthetic-only navigation experiment. Never packaged for challenge runs."""
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.async_api import async_playwright

from hackathon_toolkit.rfq.browser import BrowserSession
from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.runtime import Agent, BrowserWorker, ModelClient, agent_loop


class MeteredTransport(httpx.AsyncBaseTransport):
    """Include response bodies, failed requests and cancellation in model timings."""
    def __init__(self, metrics, transport=None):
        self.metrics = metrics
        self.transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        self.metrics["model_calls"] += 1
        started = time.monotonic()
        try:
            response = await self.transport.handle_async_request(request)
            await response.aread()
            return response
        finally:
            self.metrics["model_seconds"] += time.monotonic() - started

    async def aclose(self):
        await self.transport.aclose()


@dataclass(frozen=True)
class Fixture:
    product: str
    stock: int
    search_path: str
    result_path: str
    layout: int
    modal: bool

    def render(self, path):
        url = urlsplit(path)
        if url.path == "/":
            link = f'<a href="{self.search_path}">Materialsuche / Inventory search</a>'
            if self.layout:
                link = '<button onclick="document.querySelector(\'nav\').hidden=false">Lagerverwaltung</button><nav hidden>' + link + '</nav>'
            body = '<h1>Operations</h1><button>Help</button>' + link
            if self.modal:
                body += '<dialog id="survey"><p>Optional survey</p><button onclick="this.closest(\'dialog\').remove()">Dismiss survey</button></dialog><script>document.querySelector("dialog").showModal()</script>'
        elif url.path == self.search_path:
            body = f'<h1>Material search</h1><form action="{self.result_path}"><label>Component code <input name="q"></label><button>Search records</button></form>'
        elif url.path == self.result_path and parse_qs(url.query).get("q") == [self.product]:
            body = f'<h1>Selected result</h1><table><tr><th>Component</th><th>Stock pieces</th></tr><tr><td>{self.product}</td><td>{self.stock}</td></tr></table>'
        else:
            body = '<h1>No matching record</h1>'
        return '<!doctype html><html><head><title>Inventory probe</title></head><body>' + body + '</body></html>'


def fixtures(seed):
    rng = random.Random(seed)
    return [Fixture(f"FIXTURE-{rng.getrandbits(32):08x}", rng.randint(11, 99),
                    f"/{rng.getrandbits(64):016x}", f"/{rng.getrandbits(64):016x}",
                    i % 2, i >= 2) for i in range(4)]


@contextmanager
def serve(fixture):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = fixture.render(self.path).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def correct_evidence(book, fixture, root):
    """Check source URL and exact tokens independently of either agent's success flag."""
    for fact in book.facts.values():
        observation = book.observations[fact["observation_id"]]
        url = urlsplit(observation["url"])
        quote = fact["quote"]
        if (url.netloc == urlsplit(root).netloc and url.path == fixture.result_path
                and parse_qs(url.query).get("q") == [fixture.product]
                and fixture.product in quote
                and re.search(rf"(?<!\d){fixture.stock}(?!\d)", quote)):
            return True
    return False


async def browser_use_probe(worker, model, endpoint, root, seconds, max_steps, flash_mode=False):
    # Optional dependency is imported only for this development experiment.
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    from browser_use import ActionResult, Agent as BUAgent, Browser, ChatOpenAI, Tools

    tools = Tools(exclude_actions=["search", "write_file", "read_file", "replace_file", "evaluate"])

    @tools.action(description="Read current page as source evidence. Returns an observation_id and exact text for citations.")
    async def observe_evidence() -> ActionResult:
        rows = worker.browser.page_list()
        page = next((r["page"] for r in reversed(rows) if r.get("url", "").startswith(root)), 0)
        observation = await worker.dispatch("browser", {"operation": "observe", "page": page})
        return ActionResult(extracted_content=json.dumps(observation))

    @tools.action(description="Save an exact quote from observe_evidence. Use before finishing; invented or paraphrased quotes fail.")
    async def cite_evidence(observation_id: str, quote: str) -> ActionResult:
        result = await worker.dispatch("cite", {"observation_id": observation_id,
                                               "quote": quote, "meaning": "Requested stock record"})
        return ActionResult(extracted_content=json.dumps(result))

    llm = ChatOpenAI(model=model.model, base_url=model.base_url, api_key=model.api_key,
                     temperature=0, timeout=min(45, seconds), max_retries=0,
                     http_client=model.client, max_completion_tokens=8000)
    browser = Browser(cdp_url=endpoint, keep_alive=True, allowed_domains=[root.rstrip("/")])
    agent = BUAgent(task=worker.task + " Use observe_evidence, then cite_evidence with the exact result row before done.",
                    llm=llm, browser=browser, tools=tools, use_vision=False,
                    max_actions_per_step=5, max_failures=2, llm_timeout=min(45, seconds),
                    step_timeout=min(60, seconds), generate_gif=False, use_judge=False,
                    flash_mode=flash_mode)
    try:
        history = await agent.run(max_steps=max_steps)
        worker.done = bool(history.is_successful())
        return {"reported": worker.done, "steps": len(history.history)}
    finally:
        try:
            async with asyncio.timeout(10):
                await browser.stop()
        finally:
            await agent.close()


async def attempt(backend, fixture, root, args, directory):
    book = EvidenceBook()
    metrics = {"model_calls": 0, "model_seconds": 0.0}

    with tempfile.TemporaryDirectory(prefix="rfq-bu-probe-") as profile:
        process = subprocess.Popen([args.chrome, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                                    "--no-first-run", "--remote-debugging-port=0",
                                    f"--user-data-dir={profile}", "about:blank"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port_file = Path(profile) / "DevToolsActivePort"
            for _ in range(200):
                if port_file.exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError("Chrome exited before CDP became ready")
                await asyncio.sleep(.05)
            endpoint = "http://127.0.0.1:" + port_file.read_text().splitlines()[0]
            async with async_playwright() as pw, httpx.AsyncClient(
                    transport=MeteredTransport(metrics)) as client:
                browser = await BrowserSession.connect(pw, [endpoint], book, [root])
                parent = Agent(browser, book, {"brief": "Synthetic stock lookup. No bid or submission.",
                    "access": [{"url": root}], "submission": {"url": root}, "answer_schema": {}})
                task = f"Open {root}, discover inventory search, search component {fixture.product}, cite the row including stock, and report. Do not guess paths. Ignore unrelated controls."
                worker = BrowserWorker(parent, 0, task)
                model = ModelClient(client, os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8765/qwen/v1"),
                                    os.environ.get("QWEN_API_KEY", "local"),
                                    model=os.environ.get("QWEN_MODEL", "qwen"))
                started = time.monotonic()
                error = None
                details = {}
                try:
                    async with asyncio.timeout(args.seconds):
                        if backend == "browser-use":
                            details = await browser_use_probe(worker, model, endpoint, root, args.seconds,
                                                              args.max_steps, args.flash_mode)
                        else:
                            await agent_loop(worker, model, seconds=args.seconds, max_steps=args.max_steps)
                except Exception as exc:
                    error = type(exc).__name__
                    # Synthetic pages only; still redact the configured model credential.
                    details["error_detail"] = str(exc).replace(model.api_key, "[REDACTED]")[:1000]
                elapsed = time.monotonic() - started
                (directory / "evidence.json").write_text(json.dumps(book.dump(), indent=2))
                return {"backend": backend, "elapsed_seconds": round(elapsed, 3),
                        "reported": worker.done, "cited_correct_record": correct_evidence(book, fixture, root),
                        "error": error, "layout": fixture.layout, "modal": fixture.modal,
                        **details, **metrics}
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


async def main(args):
    if not args.chrome:
        raise ValueError("Install Chrome or pass --chrome")
    output = Path(args.artifacts) / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"seed": args.seed, "seconds": args.seconds, "repeats": args.repeats,
                "cases": args.cases, "backend": args.backend, "max_steps": args.max_steps,
                "model": os.environ.get("QWEN_MODEL", "qwen"), "clef": False,
                "browser_use_settings": {"use_vision": False, "use_judge": False,
                                         "flash_mode": args.flash_mode,
                                         "max_actions_per_step": 5, "max_failures": 2},
                "browser_use": importlib.metadata.version("browser-use") if args.backend != "current" else None}
    (output / "config.json").write_text(json.dumps(metadata, indent=2))
    outcomes = []
    for repeat in range(args.repeats):
        for index, fixture in enumerate(fixtures(args.seed + repeat)[:args.cases]):
            backends = ["current", "browser-use"] if args.backend == "both" else [args.backend]
            if (repeat + index) % 2:
                backends.reverse()
            with serve(fixture) as root:
                for backend in backends:
                    directory = output / f"{repeat}-{index}-{backend}"
                    directory.mkdir()
                    result = await attempt(backend, fixture, root, args, directory)
                    result.update(repeat=repeat, case=index)
                    outcomes.append(result)
                    (output / "outcomes.json").write_text(json.dumps(outcomes, indent=2))
                    print(json.dumps({"probe": result, "artifacts": str(output)}), flush=True)
    if not all(row["reported"] and row["cited_correct_record"] and not row["error"] for row in outcomes):
        raise SystemExit(1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["both", "current", "browser-use"], default="both")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--seconds", type=float, default=150)
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--flash-mode", action="store_true", help="Use browser-use's shorter reasoning/output mode")
    parser.add_argument("--chrome", default=shutil.which("google-chrome"))
    parser.add_argument("--artifacts", default=".rfq-artifacts/browser-use-probe")
    args = parser.parse_args()
    if args.repeats < 1 or args.seconds <= 0 or args.max_steps < 1:
        parser.error("repeats, seconds and max-steps must be positive")
    return args


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
