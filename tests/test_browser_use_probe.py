"""The experiment's score must depend on source evidence, not agent self-report."""
import importlib.util
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

from hackathon_toolkit.rfq.evidence import EvidenceBook

spec = importlib.util.spec_from_file_location("browser_use_probe", Path(__file__).parents[1] / "scripts/probe_browser_use.py")
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


async def test_metrics_count_failed_and_successful_requests():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("slow response")
        return httpx.Response(200, json={"ok": True})

    metrics = {"model_calls": 0, "model_seconds": 0.0}
    transport = probe.MeteredTransport(metrics, httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("http://proxy/test")
        assert (await client.get("http://proxy/test")).json() == {"ok": True}
    assert metrics["model_calls"] == 2
    assert metrics["model_seconds"] > 0


def test_paired_fixtures_repeat_and_cover_layouts():
    cases = probe.fixtures(42)
    assert cases == probe.fixtures(42)
    assert cases != probe.fixtures(43)
    assert {(f.layout, f.modal) for f in cases} == {(0, False), (1, False), (0, True), (1, True)}
    for fixture in cases:
        assert fixture.product not in fixture.render("/")
        assert "No matching record" in fixture.render(fixture.result_path + "?q=wrong")
        assert fixture.product in fixture.render(fixture.result_path + "?q=" + fixture.product)


@pytest.mark.parametrize("source,stock,accepted", [
    ("result", "exact", True), ("result", "prefix", False),
    ("foreign", "exact", False), ("home", "exact", False), ("wrong_query", "exact", False),
])
def test_success_requires_correct_source_and_stock(source, stock, accepted):
    fixture = probe.fixtures(42)[0]
    root = "http://127.0.0.1:1234/"
    url = root.rstrip("/") + fixture.result_path + "?q=" + fixture.product
    if source == "foreign":
        url = url.replace(":1234", ":4321")
    elif source == "home":
        url = root
    elif source == "wrong_query":
        url = url.replace(fixture.product, "other")
    quantity = str(fixture.stock) + ("0" if stock == "prefix" else "")
    quote = f"{fixture.product}\t{quantity}"
    book = EvidenceBook()
    observation = book.observe(url, quote)
    assert not probe.correct_evidence(book, fixture, root)
    book.cite(observation, quote, "Stock")
    assert probe.correct_evidence(book, fixture, root) is accepted


def test_invented_quote_cannot_be_scored():
    fixture = probe.fixtures(42)[0]
    book = EvidenceBook()
    observation = book.observe("http://127.0.0.1:1234/", "No matching record")
    with pytest.raises(ValueError, match="exact nonempty"):
        book.cite(observation, f"{fixture.product}\t{fixture.stock}", "Invented stock")


async def test_adapter_preserves_citations_and_closes_on_deadline(monkeypatch):
    book = EvidenceBook()
    fixture = probe.fixtures(42)[0]
    root = "http://127.0.0.1:1234/"
    text = f"{fixture.product}\t{fixture.stock}"
    closed = AsyncMock()
    seen = {}

    class Tools:
        def __init__(self, **kwargs):
            self.actions = {}

        def action(self, **kwargs):
            def register(fn):
                self.actions[fn.__name__] = fn
                return fn
            return register

    class Agent:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]

        async def run(self, **kwargs):
            result = await self.tools.actions["observe_evidence"]()
            observation = json.loads(result.extracted_content)
            await self.tools.actions["cite_evidence"](observation["observation_id"], text)
            await asyncio.Event().wait()

        close = closed

    def model(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "browser_use", SimpleNamespace(
        Tools=Tools, Agent=Agent, ActionResult=SimpleNamespace,
        Browser=lambda **kwargs: SimpleNamespace(stop=AsyncMock()), ChatOpenAI=model))

    async def dispatch(name, args):
        if name == "browser":
            url = root.rstrip("/") + fixture.result_path + "?q=" + fixture.product
            return {"observation_id": book.observe(url, text), "text": text}
        return book.cite(args["observation_id"], args["quote"], args["meaning"])

    worker = SimpleNamespace(task="Stock lookup", done=False, dispatch=dispatch,
        browser=SimpleNamespace(page_list=lambda: [{"page": 0, "url": root}]))
    client = object()
    model_config = SimpleNamespace(model="qwen", base_url="http://proxy/v1", api_key="test", client=client)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(.05):
            await probe.browser_use_probe(worker, model_config, "http://cdp", root, 1, 5)
    assert seen["http_client"] is client
    assert seen["base_url"] == "http://proxy/v1"
    assert probe.correct_evidence(book, fixture, root)
    closed.assert_awaited_once()
