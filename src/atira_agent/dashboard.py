from __future__ import annotations

import asyncio
import json

from aiohttp import web

HTML = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Atira multi-agent monitor</title><style>
:root{color-scheme:dark;font:14px system-ui;background:#101820;color:#e5eef5}body{margin:20px;max-width:1800px}header{display:flex;gap:20px;align-items:center}#timer{margin-left:auto;font:22px monospace}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{background:#192632;padding:12px;border-radius:9px;min-height:190px}.card img{width:100%;height:210px;object-fit:contain;background:#0c131a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px ui-monospace,monospace}#events{height:330px;overflow:auto}.label{color:#72d4cd}.small{font-size:12px;color:#a2b8c9}@media(max-width:900px){.grid{grid-template-columns:1fr}}</style>
<header><h1>Atira / multi-agent investigation</h1><span id="stage" class="label">Connecting</span><span id="timer"></span></header>
<div id="agents" class="grid"></div><section class="card"><h2>Shared evidence and pricing</h2><pre id="shared">Waiting for evidence</pre></section><section class="card"><h2>Shared event timeline</h2><div id="events"></div></section>
<p class="small">Local only. Each image is sanitized; slow or disconnected viewers do not block the agents.</p><script>
const $=id=>document.getElementById(id), cards={};let remaining=0,updated=Date.now();
function card(agent){if(cards[agent])return cards[agent];let e=document.createElement('section');e.className='card';e.innerHTML='<h2>'+agent+'</h2><img alt="Latest sanitized browser screen"><p class="status"></p><pre class="detail"></pre>';$('agents').append(e);return cards[agent]=e}
function render(e){let a=e.agent||'orchestrator',c=card(a);if(e.stage)$('stage').textContent=e.stage;if(e.remaining!==undefined){remaining=e.remaining;updated=Date.now()}if(e.event==='screenshot'&&e.path)c.querySelector('img').src='/artifact/'+encodeURIComponent(a)+'/'+encodeURIComponent(e.path)+'?t='+Date.now();c.querySelector('.status').textContent=(e.event||'')+' '+(e.summary||e.error||'');c.querySelector('.detail').textContent=(e.url||'')+'\n'+(e.site||'');if(e.event==='pricing_computed'||e.event==='evidence_status')$('shared').textContent=JSON.stringify(e.result||{counts:e.counts,unresolved:e.unresolved},null,2);let row=document.createElement('div');row.textContent='['+Number(e.elapsed||0).toFixed(1)+'s] '+a+' · '+e.event+' '+(e.summary||e.error||'');$('events').append(row);while($('events').children.length>400)$('events').firstChild.remove();$('events').scrollTop=$('events').scrollHeight}
fetch('/state').then(r=>r.json()).then(s=>{Object.entries(s.agents||{}).forEach(([name,state])=>{card(name);render({...state,agent:name});if(state.screenshot)cards[name].querySelector('img').src='/artifact/'+encodeURIComponent(name)+'/'+encodeURIComponent(state.screenshot)});if(s.shared)$('shared').textContent=JSON.stringify(s.shared,null,2)});new EventSource('/events').onmessage=e=>render(JSON.parse(e.data));setInterval(()=>{let t=Math.max(0,Math.floor(remaining-(Date.now()-updated)/1000));$('timer').textContent=Math.floor(t/60)+':'+String(t%60).padStart(2,'0')+' remaining'},1000);
</script></html>"""


class Dashboard:
    def __init__(self, telemetry, port=8787):
        self.telemetries = telemetry if isinstance(telemetry, (list, tuple)) else [telemetry]
        self.port, self.runner = port, None

    async def start(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/state", self.state)
        app.router.add_get("/events", self.events)
        app.router.add_get("/artifact/{agent}/{name}", self.artifact)
        app.router.add_get("/artifact/{name}", self.artifact)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self.port

    async def index(self, request):
        return web.Response(text=HTML, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def state(self, request):
        agents = {item.agent: item.state for item in self.telemetries}
        root = self.telemetries[0].state
        # Preserve the one-agent JSON shape for offline tools and older tests.
        payload = dict(root)
        payload.update({"agents": agents, "shared": {key: root.get(key) for key in ("pricing_result", "evidence_status", "latest_evidence") if key in root}})
        return web.json_response(payload)

    async def artifact(self, request):
        agent = request.match_info.get("agent")
        name = request.match_info["name"]
        telemetry = next((item for item in self.telemetries if item.agent == agent), self.telemetries[0])
        path = (telemetry.trace_dir / name).resolve()
        if not path.is_relative_to(telemetry.trace_dir.resolve()) or path.suffix != ".png" or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def events(self, request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        queue = asyncio.Queue(maxsize=100)
        for telemetry in self.telemetries:
            telemetry.queues.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    payload = "data: " + json.dumps(event, default=str) + "\n\n"
                except TimeoutError:
                    payload = ": heartbeat\n\n"
                await asyncio.wait_for(response.write(payload.encode()), timeout=2)
        except (ConnectionError, TimeoutError, asyncio.CancelledError):
            pass
        finally:
            for telemetry in self.telemetries:
                telemetry.queues.discard(queue)
        return response

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
