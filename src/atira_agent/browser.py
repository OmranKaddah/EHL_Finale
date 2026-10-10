from __future__ import annotations

import asyncio
import base64
import difflib
import io
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from PIL import Image
from playwright.async_api import TimeoutError as BrowserTimeoutError
from playwright.async_api import async_playwright

from .contracts import InspectionCitation, InspectionResult, Observation
from .documents import MAX_DOCUMENT_BYTES, read_document

CONTROL_SELECTOR = "a,button,input,textarea,select,[role=button],[role=link],[role=checkbox],[role=combobox],[contenteditable=true],summary"
CONTROL_INFO = """e => {
 const r=e.getBoundingClientRect(), s=getComputedStyle(e);
 if (!r.width || !r.height || s.visibility==='hidden' || s.display==='none') return null;
 const modal=document.querySelector('dialog[open],[role=dialog][aria-modal=true]');
 const labels=e.labels ? [...e.labels].map(x=>x.innerText).join(' ') : '';
 const row=e.closest('tr,[role=row],li,[role=listitem],article,details');
 return {tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),type:e.getAttribute('type'),
 label:e.getAttribute('aria-label')||labels||e.getAttribute('placeholder')||e.innerText||e.title||e.name||'',
 title:e.title||null,expanded:e.getAttribute('aria-expanded')||(e.tagName==='SUMMARY'?String(e.parentElement.open):null),
 context:row?row.innerText.slice(0,450):null,
 value:e.type==='password'?'':e.value,filled:!!e.value,href:e.href||null,checked:e.checked,disabled:e.disabled,
 blocked_by_modal:!!modal&&!modal.contains(e),inside_modal:!!modal&&modal.contains(e),
 options:e.tagName==='SELECT'?[...e.options].map(o=>({label:o.text,value:o.value})):undefined,
 x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
}"""
TAN_PATTERN = re.compile(r"(?i)\b(?:signatur[- ]?)?TAN\b[^\d\n]{0,45}([0-9]{4,10})\b")


def origin(url: str) -> tuple:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class BrowserSession:
    def __init__(self, config, run, telemetry, *, headful=True, browser_index=0, agent_id="",
                 assigned_site=None, allow_submission=False):
        self.config, self.run, self.telemetry = config, run, telemetry
        self.headful = headful
        self.browser_index, self.agent_id = browser_index, agent_id
        self.assigned_site, self.allow_submission = assigned_site, allow_submission
        scoped_access = [x for x in run.access if assigned_site is None or x.siteId == assigned_site]
        self.allowed = {origin(x.url) for x in scoped_access}
        if allow_submission:
            self.allowed.add(origin(run.submission.url))
        self.playwright = self.browser = self.context = None
        self.pages = []
        self.tab = 0
        self.frame_index = 0
        self.refs = {}
        self.observation_number = 0
        self.last_observation = None
        self.raw_text: dict[str, str] = {}
        self.dialogs = []
        self.downloads: dict[str, dict] = {}
        self.download_tasks: set[asyncio.Task] = set()
        self.secret_values = {}
        self.tan_requested_at = None
        self.tan_request_observation = 0
        self.tan_captured_at = None
        self.latest_tan = None
        self.last_screenshot = 0.0
        self.last_image = None
        self.last_image_size = None
        for site in scoped_access:
            for key, value in site.credentials.items():
                self.secret_values[f"{site.siteId}:{key}"] = (value, origin(site.url))
                telemetry.redactor.add(value)

    async def start(self):
        self.playwright = await async_playwright().start()
        if self.config.cdp_urls:
            if self.browser_index >= len(self.config.cdp_urls):
                raise RuntimeError(f"Browser {self.browser_index + 1} was not supplied by the runtime")
            self.browser = await self.playwright.chromium.connect_over_cdp(
                self.config.cdp_urls[self.browser_index], timeout=20000)
            self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        else:
            if self.config.sandbox:
                raise RuntimeError("Cannot launch a sandbox browser")
            self.browser = await self.playwright.chromium.launch(headless=not self.headful)
            self.context = await self.browser.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True)
        self.context.set_default_timeout(6000)
        self.context.set_default_navigation_timeout(20000)
        await self.context.route("**/*", self._route)
        self.context.on("page", self._register_page)
        for page in self.context.pages:
            self._register_page(page)
        if not self.pages:
            await self.context.new_page()
        return self

    async def _route(self, route):
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")) or origin(url) in self.allowed:
            await route.continue_()
        else:
            await route.abort()

    def expand_to_run_access(self):
        """Emergency coordinator fallback: reuse this supplied browser sequentially.

        This never creates a fifth browser and is invoked only after multiple
        specialists fail before the submission reserve.
        """
        for site in self.run.access:
            self.allowed.add(origin(site.url))
            for key, value in site.credentials.items():
                self.secret_values[f"{site.siteId}:{key}"] = (value, origin(site.url))
        self.telemetry.emit("browser_scope_expanded", reason="multi_agent_failure_fallback")

    def _register_page(self, page):
        if page in self.pages:
            return
        self.pages.append(page)
        page.on("dialog", lambda dialog: self.dialogs.append(dialog))
        page.on("download", self._download)

    def _download(self, download):
        task = asyncio.create_task(self._save_download(download))
        self.download_tasks.add(task)
        task.add_done_callback(self.download_tasks.discard)

    async def _save_download(self, download):
        try:
            path = await download.path()
            if not path or Path(path).stat().st_size > MAX_DOCUMENT_BYTES:
                raise ValueError("Downloaded file exceeds extraction limit")
            data = Path(path).read_bytes()
            identifier = f"d{len(self.downloads) + 1}"
            self.downloads[identifier] = {"name": download.suggested_filename, "data": data, "url": download.url}
            self.telemetry.emit("document_available", document=identifier, name=download.suggested_filename)
        except Exception as exc:
            self.telemetry.emit("tool_error", error=str(exc))

    @property
    def page(self):
        if self.pages[self.tab].is_closed():
            self.tab = next((i for i, x in enumerate(self.pages) if not x.is_closed()), 0)
        return self.pages[self.tab]

    def _url(self, value):
        url = urljoin(self.page.url, value)
        if origin(url) not in self.allowed or urlsplit(url).username or urlsplit(url).password:
            raise ValueError("Navigation must stay on the runtime-provided websites")
        return url

    def _ref(self, reference):
        if reference not in self.refs:
            raise ValueError("Stale or unknown control reference; observe again")
        return self.refs[reference]

    async def _click(self, element):
        try:
            await element.click(no_wait_after=True)
        except BrowserTimeoutError as exc:
            # A clipped iframe can make a DOM-visible button unreachable by mouse. Keyboard activation
            # is still a normal UI action. Only recover a pre-dispatch viewport failure, never an
            # uncertain click/navigation or a control blocked by another modal.
            clipped = await element.evaluate("e => {const r=e.getBoundingClientRect(); return r.left>=innerWidth || r.top>=innerHeight || r.right<=0 || r.bottom<=0}")
            viewport_failure = "outside of the viewport" in str(exc) or (clipped and "intercepts pointer events" in str(exc))
            blocked = await element.evaluate("e => {const m=document.querySelector('dialog[open],[role=dialog][aria-modal=true]'); return !!m && !m.contains(e)}")
            if not viewport_failure or blocked or not await element.is_enabled():
                raise
            info = await element.evaluate("e => ({tag:e.tagName,type:e.type,role:e.getAttribute('role')})")
            if info["tag"] not in {"BUTTON", "A"} and info["role"] not in {"button", "link"} and info["type"] not in {"checkbox", "radio", "button", "submit"}:
                raise
            await element.focus()
            if not await element.evaluate("e => document.activeElement === e"):
                raise
            await element.press("Space" if info["type"] in {"checkbox", "radio"} else "Enter", timeout=1500)
            self.telemetry.emit("browser_recovered", method="keyboard_activation", reason="clipped observed control")

    async def inspect_controls(self, references):
        """Inspect a model-selected set of independent controls, observing after EVERY click."""
        if not isinstance(references, list) or not 1 <= len(references) <= 8 or len(set(references)) != len(references):
            raise ValueError("Select one to eight distinct currently observed controls")
        if self.last_observation is None:
            raise ValueError("Observe before selecting controls to inspect")
        controls = {item["ref"]: item for item in self.last_observation.controls}
        selected = [(ref, self._ref(ref), controls.get(ref, {})) for ref in references]
        before = self.last_observation
        urls = [frame.url for frame in self.page.frames]
        tab_count = len(self.pages)
        for ref, element, control in selected:
            if self.dialogs or len(self.pages) != tab_count or [f.url for f in self.page.frames] != urls:
                raise ValueError("Inspection changed page/tab/dialog; observe and choose the next action")
            if not await element.evaluate("e => e.isConnected"):
                raise ValueError("Selected inspection control became stale; observe again")
            await self._click(element)
            after = await self.observe()
            additions = [line[2:] for line in difflib.ndiff(before.text.splitlines(), after.text.splitlines())
                         if line.startswith("+ ")]
            revealed = "\n".join(additions)
            yield after, InspectionResult(
                clicked_ref=ref,
                control_label=str(control.get("label") or ""),
                control_context=control.get("context"),
                before_observation=before.id,
                after_observation=after.id,
                revealed_text=revealed,
                citation_candidates=self._inspection_citations(before, after, control, additions),
                dialog=after.dialog,
            )
            before = after

    @staticmethod
    def _inspection_citations(before, after, control, additions) -> list[InspectionCitation]:
        """Return only excerpts that are exact visible text in their observation.

        Dates, tooltip bodies and row labels can occupy separate, mutually
        exclusive UI states.  Returning both source IDs makes that relationship
        durable without turning this generic browser helper into a Q&A parser.
        """
        candidates: list[InspectionCitation] = []
        seen: set[tuple[str, str]] = set()

        def add(observation, value):
            if not isinstance(value, str):
                return
            value = value.strip()
            if len(value) < 3:
                return
            # The ledger permits whitespace-normalized exact visible excerpts.
            # Prefer a whole visible line when a context block is not contiguous.
            options = [value, *(line.strip() for line in value.splitlines())]
            for excerpt in options:
                if len(excerpt) < 3 or excerpt not in observation.text:
                    continue
                key = (observation.id, excerpt)
                if key not in seen:
                    seen.add(key)
                    candidates.append(InspectionCitation(observation=observation.id, excerpt=excerpt[:1200]))
                return

        add(before, control.get("context"))
        add(before, control.get("label"))
        for line in additions:
            add(after, line)
        return candidates

    async def read_links(self, references):
        """Visit only explicitly selected, currently observed hyperlinks; never discover more links."""
        if not isinstance(references, list) or not 1 <= len(references) <= 6 or len(set(references)) != len(references):
            raise ValueError("Select one to six distinct observed record links")
        selected = []
        for ref in references:
            self._ref(ref)
            control = next(x for x in self.last_observation.controls if x["ref"] == ref)
            if not control.get("href"):
                raise ValueError("Selected control has no observed hyperlink; inspect it with click instead")
            selected.append((control["label"], self._url(control["href"])))
        original_tab = self.tab
        try:
            for label, url in selected:
                await self.act("navigate", {"url": url, "new_tab": True})
                observation = await self.observe()
                yield observation, {"selected_label": label, "observation": observation.id, "tab": self.tab,
                                    "url": observation.url, "text": observation.text[:18000],
                                    "truncated": len(observation.text) > 18000}
        finally:
            self.tab = original_tab
            await self.page.bring_to_front()

    async def observe(self, include_image=False) -> Observation:
        # An image from an earlier observation must never ground a new pixel action.
        self.last_image = None
        self.last_image_size = None
        self.observation_number += 1
        oid = f"{self.agent_id + '-' if self.agent_id else ''}o{self.observation_number}"
        self.refs = {}
        controls, frames, texts = [], [], []
        if not self.dialogs:
            for frame_index, frame in enumerate(self.page.frames):
                frames.append({"frame": frame_index, "url": frame.url, "name": frame.name})
                try:
                    body = await frame.locator("body").inner_text(timeout=2000)
                    texts.append(f"[frame {frame_index}]\n{body}")
                    # Canvas-rendered gates and diagrams can expose their only
                    # readable description through accessibility metadata.
                    semantics = await frame.locator("canvas[aria-label],[role=img][aria-label]").evaluate_all(
                        "els => els.slice(0, 20).map(e => e.getAttribute('aria-label')).filter(Boolean)")
                    if semantics:
                        texts.append("[accessible visual descriptions]\n" + "\n".join(map(str, semantics)))
                    elements = await frame.query_selector_all(CONTROL_SELECTOR)
                    for index, element in enumerate(elements[:350]):
                        info = await element.evaluate(CONTROL_INFO)
                        if info is None:
                            continue
                        ref = f"{oid}-f{frame_index}-e{index}"
                        self.refs[ref] = element
                        info.update({"ref": ref, "frame": frame_index})
                        info["label"] = str(info["label"])[:250]
                        controls.append(info)
                except Exception as exc:
                    texts.append(f"[frame {frame_index} unavailable: {type(exc).__name__}]")
        raw = "\n".join(texts)
        for match in TAN_PATTERN.finditer(raw):
            self.telemetry.redactor.add(match.group(1))
        self.raw_text[oid] = raw
        if len(self.raw_text) > 20:
            self.raw_text.pop(next(iter(self.raw_text)))
        dialog = {"type": self.dialogs[0].type, "message": self.dialogs[0].message} if self.dialogs else None
        text = self.telemetry.redactor.text(raw[:36000])
        if dialog:
            text += "\n[Browser dialog] " + self.telemetry.redactor.text(dialog["message"])
        obs = Observation(id=oid, action_id=self.telemetry.action_id, tab=self.tab,
                          url=self.telemetry.redactor.text(self.page.url), title=await self.page.title() if not dialog else "Dialog open",
                          text=text, controls=self.telemetry.redactor.clean(controls), frames=self.telemetry.redactor.clean(frames),
                          tabs=[{"tab": i, "url": self.telemetry.redactor.text(p.url)} for i, p in enumerate(self.pages) if not p.is_closed()],
                          dialog=self.telemetry.redactor.clean(dialog), documents=[{"id": k, "name": v["name"]} for k, v in self.downloads.items()])
        self.last_observation = obs
        self.telemetry.tab = self.tab
        self.telemetry.site = urlsplit(self.page.url).hostname or ""
        self.telemetry.emit("observation", id=oid, url=obs.url, title=obs.title, text=text, controls=obs.controls,
                            frames=obs.frames, tabs=obs.tabs, dialog=obs.dialog, documents=obs.documents)
        if not dialog and (include_image or time.monotonic() - self.last_screenshot >= 4):
            await self.screenshot(raw)
        return obs

    async def screenshot(self, raw=None):
        raw = raw if raw is not None else "\n".join(self.raw_text.values())
        self.last_image = None
        # Mask matching text in every frame; omit the image if a secret cannot be located reliably.
        masks = [frame.locator("input,textarea,[contenteditable=true]") for frame in self.page.frames]
        for secret in self.telemetry.redactor.secrets:
            if secret not in raw:
                continue
            found = False
            for frame in self.page.frames:
                locator = frame.get_by_text(secret, exact=False)
                if await locator.count():
                    masks.append(locator)
                    found = True
            if not found:
                self.telemetry.emit("screenshot_omitted", reason="unlocatable sensitive text")
                return None
        if TAN_PATTERN.search(raw):
            self.telemetry.emit("screenshot_omitted", reason="signing message")
            return None
        if await self.page.locator('input[type="password"]:visible').count():
            self.telemetry.emit("screenshot_omitted", reason="login form")
            return None
        try:
            # Mask editable values, including usernames/TANs, even when a page does not label them correctly.
            data = await self.page.screenshot(type="png", mask=masks, timeout=4000)
            with Image.open(io.BytesIO(data)) as image:
                self.last_image_size = image.size
            filename = f"screen-{self.telemetry.action_id:05d}.png"
            (self.telemetry.trace_dir / filename).write_bytes(data)
            self.last_image = base64.b64encode(data).decode()
            self.last_screenshot = time.monotonic()
            self.telemetry.emit("screenshot", path=filename)
            return filename
        except Exception:
            return None

    async def act(self, name: str, args: dict):
        if name == "navigate":
            url = self._url(args["url"])
            if args.get("new_tab"):
                page = await self.context.new_page()
                self.tab = self.pages.index(page)
            try:
                await self.page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                if "Download is starting" not in str(exc):
                    raise
            self.telemetry.emit("browser_navigated", url=url)
        elif name == "tab":
            number = int(args["tab"])
            if not 0 <= number < len(self.pages) or self.pages[number].is_closed():
                raise ValueError("Unknown tab")
            self.tab = number
            await self.page.bring_to_front()
        elif name == "frame":
            self.frame_index = int(args["frame"])
            if not 0 <= self.frame_index < len(self.page.frames):
                raise ValueError("Unknown frame")
        elif name in {"click", "fill", "select", "check", "press"}:
            element = self._ref(args["ref"])
            if name == "click":
                await self._click(element)
            elif name == "fill":
                value = str(args.get("text", ""))
                if args.get("secret"):
                    if args["secret"] not in self.secret_values:
                        raise ValueError("Use an opaque credential handle from sites.credential_handles, not a masked value")
                    value, allowed_origin = self.secret_values[args["secret"]]
                    frame = await element.owner_frame()
                    if origin(frame.url) != allowed_origin:
                        raise ValueError("Credential belongs to a different website")
                elif args.get("tan"):
                    if not self.latest_tan or time.monotonic() - self.tan_captured_at > 240:
                        raise ValueError("No fresh TAN captured")
                    if origin(self.page.url) != origin(self.run.submission.url):
                        raise ValueError("TAN can only be entered at the submission website")
                    value = self.latest_tan
                elif await element.get_attribute("type") == "password" or value == "[REDACTED]":
                    raise ValueError("Use the site's credential handle for passwords, never redacted text")
                await element.fill(value)
            elif name == "select":
                if "label" in args:
                    await element.select_option(label=args["label"])
                else:
                    await element.select_option(value=str(args["value"]))
            elif name == "check":
                await element.set_checked(bool(args.get("checked", True)))
            else:
                await element.press(args["key"])
        elif name == "scroll":
            pixels = max(-2000, min(2000, int(args.get("pixels", 650))))
            if not 0 <= self.frame_index < len(self.page.frames):
                raise ValueError("Selected frame is no longer available")
            await self.page.frames[self.frame_index].evaluate("pixels => window.scrollBy(0, pixels)", pixels)
        elif name == "pixel_click":
            if not self.last_image or not self.last_observation or args.get("observation") != self.last_observation.id:
                raise ValueError("Pixel clicks require the current screenshot observation")
            x, y = int(args["x"]), int(args["y"])
            if not self.last_image_size or not (0 <= x < self.last_image_size[0] and 0 <= y < self.last_image_size[1]):
                raise ValueError("Click outside screenshot")
            await self.page.mouse.click(x, y)
        elif name == "dialog":
            if not self.dialogs:
                raise ValueError("No browser dialog")
            dialog = self.dialogs.pop(0)
            if args.get("accept"):
                await dialog.accept()
            else:
                await dialog.dismiss()
        elif name == "wait":
            await asyncio.sleep(min(5, max(0, float(args.get("seconds", 1)))))
        elif name == "capture_tan":
            if self.tan_requested_at is None:
                raise ValueError("Request a signing TAN first")
            observation_id = args.get("observation", "")
            suffix = re.search(r"-?o(\d+)$", observation_id)
            if not suffix or int(suffix.group(1)) <= self.tan_request_observation:
                raise ValueError("Read the newly requested signing message; cached TAN observations are invalid")
            raw = self.raw_text.get(observation_id, "")
            matches = list(TAN_PATTERN.finditer(raw))
            if len(matches) != 1:
                raise ValueError("Open the specific new signing message with one visible TAN")
            self.latest_tan = matches[0].group(1)
            self.tan_captured_at = time.monotonic()
            self.telemetry.redactor.add(self.latest_tan)
            return {"captured": True, "instruction": "Use fill with tan=true. The value stays secret."}
        elif name in {"observe", "screenshot"}:
            pass
        else:
            raise ValueError(f"Unknown browser action {name}")
        if name not in {"wait", "observe", "screenshot", "frame"}:
            await asyncio.sleep(0.25)
        return {"ok": True}

    async def document(self, args):
        if self.download_tasks:
            await asyncio.wait(self.download_tasks, timeout=4)
        doc = self.downloads[args["id"]]
        result = await asyncio.to_thread(read_document, doc["data"], doc["name"], args.get("member"), int(args.get("page", 1)))
        self.observation_number += 1
        oid = f"o{self.observation_number}"
        text = result.get("text", str(result.get("members", "")))
        for match in TAN_PATTERN.finditer(text):
            self.telemetry.redactor.add(match.group(1))
        image = result.pop("image", None)
        self.last_image = image if image and not TAN_PATTERN.search(text) else None
        obs = Observation(id=oid, action_id=self.telemetry.action_id, tab=self.tab, url=doc["url"],
                          title=f"{doc['name']} {args.get('member', '')} page {args.get('page', 1)}",
                          text=self.telemetry.redactor.text(text), documents=[{k: v for k, v in result.items() if k != "text"}])
        self.telemetry.emit("observation", **obs.model_dump(mode="json"))
        return obs

    async def close(self):
        if self.download_tasks:
            await asyncio.wait(self.download_tasks, timeout=2)
        if self.context:
            await self.context.unroute("**/*", self._route)
        if self.browser and not self.config.cdp_urls:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
