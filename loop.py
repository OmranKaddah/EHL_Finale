"""A tool-using model loop: the model sees the page, chooses what to click, type, open and read, and reports back.
Every navigation decision is the model's; the tools only execute it and show the result."""
import asyncio
import json
import os
from urllib.parse import urlparse
import time
import traceback

import models
import webtools

MODEL = os.environ.get("AGENT_MODEL", models.QWEN_MODEL)
KEEP_FULL = 3  # tool results kept in full when the context is compacted
CONTEXT_LIMIT_CHARS = 220_000  # compact the history only above this size (keeps the prompt cache warm)
NAV = None  # (client, model, params) for navigation agents, chosen once per run; None = hosted Qwen
NAV_FALLBACK = None  # (client, model, params) used for one step when the hosted Qwen is overloaded (timeout)

BROWSER_TOOLS = [
    ("look", "Show the current page again: text plus [n] refs for every link, button and field.", {}),
    ("click", "Click element [ref].", {"ref": "integer"}),
    ("type", "Type text into the input [ref]; submit=true presses Enter afterwards.",
     {"ref": "integer", "text": "string", "submit": "boolean?"}),
    ("fill_many", "Type into several inputs at once: fields = JSON list of {\"ref\": n, \"text\": \"...\"}. Use it to "
                  "fill a whole form section in one step.", {"fields": "string"}),
    ("fill_form", "Fill a whole form section in ONE step: fields = JSON list of {\"field\": name or label, "
                  "\"value\": ...} in the order a person would fill them (dropdowns, text fields, checkboxes). For "
                  "dependent dropdowns give apply_button = the text of the button that confirms each choice (if the "
                  "form has one). Much faster than single clicks.", {"fields": "string", "apply_button": "string?"}),
    ("select", "Choose an option (its visible label or its value) in the dropdown [ref].",
     {"ref": "integer", "option": "string"}),
    ("set_checkbox", "Tick (checked=true) or untick a checkbox/radio [ref].", {"ref": "integer", "checked": "boolean"}),
    ("slide", "Drag the range slider [ref] fully to the right (unlock sliders).", {"ref": "integer"}),
    ("press", "Press a keyboard key, e.g. Enter, Escape, Tab.", {"key": "string"}),
    ("goto", "Open a URL (absolute, or a path on the current site) in this tab.", {"url": "string"}),
    ("back", "Browser back.", {}),
    ("read_url", "Download a URL (a path on the current site, a document, a message, a ZIP, a result page, an iframe "
                 "src) with this tab's login and return its full text, including collapsed sections. Does not "
                 "navigate. Best way to read documents, messages, iframes and further result pages.", {"url": "string"}),
    ("read_page", "Full text of the current page and its frames, including hidden/collapsed sections.", {}),
    ("find", "Search the current page text for a string and show the surroundings.", {"text": "string"}),
]


async def within(coro, seconds):
    """Like asyncio.wait_for, but never waits for a stuck call to acknowledge its cancellation: it is abandoned."""
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        raise TimeoutError(f"no result within {seconds}s")
    return task.result()


def _schema(name, desc, params):
    props, req = {}, []
    for k, t in params.items():
        opt = t.endswith("?")
        props[k] = {"type": t.rstrip("?")}
        if not opt:
            req.append(k)
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": req}}}


class Agent:
    """One model with tools on one or more browser tabs (keyed by site id)."""

    def __init__(self, name: str, system: str, tabs: dict, deadline: float, extra_tools=None, max_steps=80,
                 log=print, thinking=False, call_timeout=45, client=None, model=None, model_params=None, urgent=None):
        self.name, self.system, self.tabs, self.deadline = name, system, tabs, deadline
        self.extra = extra_tools or {}  # name -> (description, params, async fn(**args) -> str)
        self.max_steps, self.log = max_steps, log
        self.urgent, self.urgent_sent = urgent, False  # (seconds_left, message) sent once near the deadline
        self.call_timeout = call_timeout
        if client is None and NAV is not None and NAV[1] != MODEL:
            client, model, model_params = NAV
            self.call_timeout = max(call_timeout, 90)
        self.client, self.model, self.model_params = client, model, model_params or {}
        self.extra_body = {} if thinking else {"chat_template_kwargs": {"enable_thinking": False}}
        self.result = None
        self.docs = {}  # url -> text of every document the model chose to read
        multi = len(tabs) > 1
        self.tools = []
        for n, d, p in BROWSER_TOOLS:
            p = dict(p)
            if multi:
                p["site"] = "string"
                d += f" site = which tab: one of {list(tabs)}."
            self.tools.append(_schema(n, d, p))
        for n, (d, p, _) in self.extra.items():
            self.tools.append(_schema(n, d, p))
        self.tools.append(_schema("finish", "Finish with your final report (all facts you were asked for, with "
                                            "sources). Call only once.", {"report": "string"}))

    async def _tool(self, name, args):
        if name == "finish":
            if not str(args.get("report", "")).strip():
                return ("ERROR: finish needs a non-empty 'report'. Your report was probably too long and got cut off. "
                        "Documents you read are attached automatically; call finish again with a SHORT structured "
                        "report (under 600 words) of the key facts.")
            check = getattr(self, "finish_check", None)
            msg = check(str(args.get("report", ""))) if check else None
            if msg:
                return msg
            budget_left = self.deadline - time.time()
            if len(self.docs) < 2 and budget_left > 120 and not getattr(self, "pushed_back", False):
                self.pushed_back = True  # giving up early is the costliest mistake: one push to keep looking
                return ("NOT ACCEPTED YET: you have read almost nothing and still have "
                        f"{budget_left / 60:.0f} minutes. Do not give up: look at the page again, try other menus, "
                        "links, document lists, search fields and further pages, open documents with read_url. "
                        "Call finish when you found what you were asked for (or the time is nearly up).")
            self.result = args["report"]
            return "Finished."
        if name in self.extra:
            return await self.extra[name][2](**args)
        site = args.get("site") or next(iter(self.tabs))
        if site not in self.tabs:
            return f"ERROR: you have no tab for '{site}'. Your tabs: {list(self.tabs)}."
        tab: webtools.Browser = self.tabs[site]
        try:  # a background tab in a headful Chrome is throttled: bring the agent's tab to the front first
            await within(tab.page.bring_to_front(), 5)
        except Exception:
            pass
        if name == "look":
            pass
        elif name == "click":
            await tab.click(int(args["ref"]))
        elif name == "type":
            await tab.fill(int(args["ref"]), args.get("text", ""), bool(args.get("submit")))
        elif name == "fill_many":
            fields = args.get("fields")
            if isinstance(fields, str):
                fields = json.loads(fields)
            for f in fields:
                await tab.fill(int(f["ref"]), str(f.get("text", "")))
        elif name == "fill_form":
            fields = args.get("fields")
            if isinstance(fields, str):
                fields = json.loads(fields)
            res = await tab.fill_form(fields, args.get("apply_button") or "")
            return res + "\n\n" + await tab.snapshot(10000)
        elif name == "select":
            await tab.select(int(args["ref"]), str(args["option"]))
        elif name == "set_checkbox":
            await tab.check(int(args["ref"]), bool(args.get("checked", True)))
        elif name == "slide":
            await tab.drag_slider(int(args["ref"]))
        elif name == "press":
            await tab.press(args["key"])
        elif name == "goto":
            url = args["url"]
            full = url if "://" in url else webtools._join(tab.page.url, url)
            home = getattr(tab, "home_host", None)
            if home and urlparse(full).netloc and urlparse(full).netloc != home:
                return (f"ERROR: this tab belongs to {home}; it cannot open {urlparse(full).netloc}. "
                        f"Use the tab of that website (your tabs: {list(self.tabs)}) or stay on this site.")
            await tab.goto(full)
        elif name == "back":
            await tab.back()
        elif name == "read_url":
            text = (await tab.fetch_text(args["url"]))[:25000]
            if args["url"] in self.docs:
                return f"(You already read {args['url']}; its text is above. Do not re-read; continue.)"
            self.docs[args["url"]] = text
            return text
        elif name == "read_page":
            return (await tab.read_page())[:30000]
        elif name == "find":
            return await tab.find_text(args["text"])
        return await tab.snapshot(10000)

    async def run(self, task: str) -> str:
        client = self.client or models.qwen()
        model = self.model or MODEL
        if model != MODEL:
            self.extra_body = {}
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": task}]
        tool_msgs = []
        for step in range(self.max_steps):
            left = self.deadline - time.time()
            if left < 0 and self.result is None:
                messages.append({"role": "user", "content": "TIME IS UP. Call finish now with everything you "
                                                            "found so far, marking unknowns as unknown."})
            # The history is append-only so the provider's prompt cache keeps working (cached input costs ~1/10).
            # Only when it grows large are older page outputs shortened once (one cache rebuild, then append again).
            if sum(len(str(m.get("content") or "")) for m in messages) > CONTEXT_LIMIT_CHARS:
                for m in tool_msgs[:-KEEP_FULL]:
                    if len(m["content"]) > 600:
                        m["content"] = m["content"][:600] + "\n...(older page output shortened)"
            try:
                params = dict(model=model, messages=messages, tools=self.tools, tool_choice="auto")
                if model == MODEL:
                    params.update(temperature=0.2, max_tokens=6000, extra_body=self.extra_body)
                else:
                    # some OpenAI models refuse reasoning_effort together with function tools
                    params.update(max_completion_tokens=16000,
                                  **{k: v for k, v in self.model_params.items() if k != "reasoning_effort"})
                try:
                    reply = await within(client.chat.completions.create(**params), self.call_timeout)
                except TimeoutError:
                    if model != MODEL or NAV_FALLBACK is None or NAV_FALLBACK[1] == MODEL:
                        raise
                    # the shared hosted model is overloaded: take this one step with the fallback model
                    fc, fm, fp = NAV_FALLBACK
                    self.log(f"[{self.name}] Qwen timeout -> this step with {fm}")
                    # only the essentials go to the (pricier) fallback model: the job, the recent steps, the page
                    recent = [m for m in messages[2:] if m.get("role") == "assistant"][-6:]
                    steps = "\n".join(
                        "; ".join(f"{c['function']['name']} {c['function']['arguments'][:150]}"
                                  for c in (m.get("tool_calls") or [])) or str(m.get("content", ""))[:200]
                        for m in recent)
                    last_tool = next((m["content"] for m in reversed(messages) if m.get("role") == "tool"), "")
                    small = messages[:2] + [{"role": "user", "content":
                        f"(Continuing your task.) Your last steps:\n{steps}\n\nThe latest result/page:\n"
                        f"{str(last_tool)[:12000]}\n\nDecide the next tool call(s)."}]
                    fparams = dict(model=fm, messages=small, tools=self.tools, tool_choice="auto",
                                   max_completion_tokens=8000,
                                   **{k: v for k, v in fp.items() if k != "reasoning_effort"})
                    reply = await within(fc.chat.completions.create(**fparams), 90)
            except Exception as e:
                self.log(f"[{self.name}] model error: {type(e).__name__} {e}")
                await asyncio.sleep(2)
                continue
            msg = reply.choices[0].message
            calls = msg.tool_calls or []
            messages.append({"role": "assistant", "content": msg.content or "",
                             **({"tool_calls": [c.model_dump() for c in calls]} if calls else {})})
            if msg.content:
                self.log(f"[{self.name}] think: {msg.content[:300]}")
            if not calls:
                if left < 0:
                    self.result = msg.content or ""
                    break
                messages.append({"role": "user", "content": "Continue using the tools. When you have everything, "
                                                            "call finish(report)."})
                continue
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except ValueError:
                    args = {}
                self.log(f"[{self.name}] {c.function.name} {json.dumps(args, ensure_ascii=False)[:200]}")
                try:
                    out = await within(self._tool(c.function.name, args), 45)
                except Exception as e:
                    out = f"ERROR: {e}"
                    try:
                        site = args.get("site") or next(iter(self.tabs))
                        out += "\n" + await within(self.tabs.get(site, next(iter(self.tabs.values()))).snapshot(8000), 20)
                    except Exception:
                        pass
                if str(out).startswith("ERROR"):
                    self.log(f"[{self.name}] tool error: {str(out)[:160]!r}")
                # a tab that stopped responding: after two hangs in a row continue in another browser
                if "no result within" in str(out):
                    self.hangs = getattr(self, "hangs", 0) + 1
                    site = args.get("site") or next(iter(self.tabs))
                    tab = self.tabs.get(site) or next(iter(self.tabs.values()))
                    try:
                        moved = self.hangs >= 2 and await within(tab.move_to_spare_browser(), 30)
                    except Exception:
                        moved = False
                    if moved:
                        self.hangs = 0
                        self.log(f"[{self.name}] tab froze; moved to another browser")
                        out = (str(out) + "\nThe tab froze and was replaced by a fresh session in another browser: "
                               "open the website again and log in.")
                else:
                    self.hangs = 0
                tm = {"role": "tool", "tool_call_id": c.id, "content": str(out)}
                messages.append(tm)
                if c.function.name not in ("read_url", "read_page", "find", "python"):
                    tool_msgs.append(tm)
            if self.result is not None:
                break
            if self.urgent and not self.urgent_sent and self.deadline - time.time() < self.urgent[0]:
                self.urgent_sent = True
                messages.append({"role": "user", "content": self.urgent[1]})
            mins = max(0, (self.deadline - time.time()) / 60)
            if 0 < mins < 1.5:
                messages.append({"role": "user", "content": f"Only {mins:.1f} min left for you: wrap up and finish."})
        self.log(f"[{self.name}] DONE: {str(self.result)[:1500]}")
        return self.result or "(no report)"
