from __future__ import annotations

import asyncio
import json

from aiohttp import web

HTML = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Atira live run</title><style>
:root{color-scheme:dark;font:15px system-ui;background:#101820;color:#e5eef5}body{margin:24px;max-width:1600px}
header{display:flex;gap:24px;align-items:center}h1{font-size:24px}#timer{margin-left:auto;font:22px monospace}
main{display:grid;grid-template-columns:1.1fr 1fr;gap:20px}section{background:#192632;padding:18px;border-radius:10px}
#screen{width:100%;min-height:150px;object-fit:contain;background:#0c131a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px ui-monospace,monospace}
#events{height:430px;overflow:auto}article{padding:8px 0;border-bottom:1px solid #30404e}.label{color:#72d4cd}
.error{color:#ffad98}#url{overflow-wrap:anywhere;color:#aac0d3}.small{font-size:12px;color:#a2b8c9}button{padding:8px;background:#263c4c;color:white;border:1px solid #526778;border-radius:5px}
@media(max-width:900px){main{grid-template-columns:1fr}} </style>
<header><h1>Atira / live investigation</h1><span id="stage" class="label">Connecting</span><span id="timer"></span></header>
<p id="url"></p><main><section><img id="screen" alt="Latest sanitized browser screenshot"><p id="action"></p>
<div id="status"></div><h3>Pricing and unresolved evidence</h3><pre id="pricing">Waiting for evidence</pre></section>
<section><h3>Run timeline</h3><div id="events"></div><h3>Latest evidence</h3><pre id="evidence"></pre></section></main>
<p class="small">Local only. Secrets and sensitive screens are omitted. The agent continues if this viewer disconnects.</p>
<script>
const $=id=>document.getElementById(id);let events=[],remaining=0,updated=Date.now();
function render(e){events.push(e);if(events.length>400)events.shift();
 if(e.stage)$('stage').textContent=e.stage;if(e.remaining!==undefined){remaining=e.remaining;updated=Date.now()}
 if(e.url)$('url').textContent=e.url;if(e.summary)$('action').textContent=e.summary;
 if(e.event==='screenshot')$('screen').src='/artifact/'+encodeURIComponent(e.path)+'?t='+Date.now();
 if(e.event==='evidence_added')$('evidence').textContent=JSON.stringify(e.evidence,null,2);
 if(e.event==='pricing_computed')$('pricing').textContent=JSON.stringify(e.result,null,2);
 if(e.submission)$('status').textContent='Submission: '+e.submission;
 const a=document.createElement('article');if(e.error)a.className='error';
 a.textContent='['+Number(e.elapsed).toFixed(1)+'s] '+e.event+' '+(e.summary||e.error||e.stage||e.message||'');
 $('events').append(a);while($('events').children.length>400)$('events').firstChild.remove();$('events').scrollTop=$('events').scrollHeight;}
fetch('/state').then(r=>r.json()).then(s=>{if(s.screenshot)$('screen').src='/artifact/'+encodeURIComponent(s.screenshot);if(s.pricing_result)$('pricing').textContent=JSON.stringify(s.pricing_result,null,2);if(s.latest_evidence)$('evidence').textContent=JSON.stringify(s.latest_evidence,null,2);render(s)});
new EventSource('/events').onmessage=e=>render(JSON.parse(e.data));
setInterval(()=>{let t=Math.max(0,Math.floor(remaining-(Date.now()-updated)/1000));$('timer').textContent=Math.floor(t/60)+':'+String(t%60).padStart(2,'0')+' remaining'},1000);
</script></html>"""


class Dashboard:
    def __init__(self, telemetry, port=8787):
        self.telemetry, self.port, self.runner = telemetry, port, None

    async def start(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/state", self.state)
        app.router.add_get("/events", self.events)
        app.router.add_get("/artifact/{name}", self.artifact)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self.port

    async def index(self, request):
        return web.Response(text=HTML, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def state(self, request):
        return web.json_response(self.telemetry.state)

    async def artifact(self, request):
        name = request.match_info["name"]
        path = (self.telemetry.trace_dir / name).resolve()
        if not path.is_relative_to(self.telemetry.trace_dir.resolve()) or path.suffix != ".png" or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def events(self, request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        queue = asyncio.Queue(maxsize=100)
        self.telemetry.queues.add(queue)
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
            self.telemetry.queues.discard(queue)
        return response

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
