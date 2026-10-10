"""Bounded browser actions selected by the model; connects only to supplied CDP browsers."""
from __future__ import annotations

import base64
import csv
import json
import math
import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from .evidence import EvidenceBook

MAX_DOCUMENT = 20 * 1024 * 1024


def origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected an HTTP(S) URL without embedded credentials")
    return f"{parts.scheme}://{parts.netloc.lower()}"


def same_origin(url: str, expected: str) -> bool:
    """Blank tabs, srcdoc and blob observations are not tender evidence."""
    try:
        return origin(url) == origin(expected)
    except ValueError:
        return False


def document_text(payload: bytes, name: str, member: str | None = None) -> str:
    """Read one selected document; ZIP members are listed until the model selects one."""
    if len(payload) > MAX_DOCUMENT:
        raise ValueError("Document exceeds 20 MiB")
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if member is None:
                return "ZIP members (select one with member):\n" + "\n".join(archive.namelist()[:500])
            info = archive.getinfo(member)
            if info.is_dir() or info.file_size > MAX_DOCUMENT or member.lower().endswith(".zip"):
                raise ValueError("Unsupported or oversized ZIP member")
            # Never extract to the filesystem; path traversal names are harmless here.
            return document_text(archive.read(info), member)
    if name.lower().endswith(".pdf") or payload.startswith(b"%PDF"):
        import pymupdf
        with pymupdf.open(stream=payload, filetype="pdf") as document:
            return "\n".join(f"[page {i + 1}]\n{page.get_text()}" for i, page in enumerate(document))
    if name.lower().endswith((".txt", ".csv", ".md", ".json", ".xml", ".html")):
        return payload.decode("utf-8-sig")
    raise ValueError("Unsupported document format; use browser rendering for this document")


class BrowserSession:
    def __init__(self, browsers, book: EvidenceBook, allowed_urls: list[str]):
        self.browsers, self.book = browsers, book
        self.origins = {origin(url) for url in allowed_urls}
        self.pages = []
        self.controls = {}
        self.observed_pages = {}
        self.generation = 0
        self.downloads = {}
        self.known_urls = set(allowed_urls)
        self.control_info = {}
        self.browser_origins = {}
        self.active_pages = {}

    @classmethod
    async def connect(cls, playwright, endpoints: list[str], book: EvidenceBook, allowed_urls: list[str]):
        if not 1 <= len(endpoints) <= 4:
            raise ValueError("Supply between one and four existing CDP browsers")
        browsers = []
        for endpoint in endpoints:
            parsed = urlsplit(endpoint)
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("CDP endpoints must be local")
            browsers.append(await playwright.chromium.connect_over_cdp(endpoint, timeout=15000))
        session = cls(browsers, book, allowed_urls)
        for browser in browsers:
            for context in browser.contexts:
                context.set_default_timeout(8000)
                context.set_default_navigation_timeout(15000)
                await context.route("**/*", session._route)
        return session

    async def _route(self, route):
        url = route.request.url
        try:
            allowed = origin(url) in self.origins
        except ValueError:
            allowed = url.startswith(("data:", "blob:", "about:"))
        await (route.continue_() if allowed else route.abort())

    def page_list(self):
        for browser in self.browsers:
            for context in browser.contexts:
                for page in context.pages:
                    if page not in self.pages:
                        self.pages.append(page)
        return [{"page": i, "browser": self.browser_index(p), "url": p.url,
                 "active": self.active_pages.get(self.browser_index(p)) == i,
                 "assigned_origin": self.browser_origins.get(self.browser_index(p))}
                for i, p in enumerate(self.pages) if not p.is_closed()]

    def preferred_page(self, browser_index):
        if type(browser_index) is not int or not 0 <= browser_index < len(self.browsers):
            raise ValueError("Unknown browser")
        rows = [row for row in self.page_list() if row["browser"] == browser_index]
        if not rows:
            raise ValueError("Browser has no open page; use new_tab in that browser")
        return next((r["page"] for r in rows if r["active"]),
                    next((r["page"] for r in rows if r["url"] != "about:blank"), rows[0]["page"]))

    def browser_index(self, page):
        return next(i for i, browser in enumerate(self.browsers) if page.context in browser.contexts)

    def page(self, index):
        self.page_list()
        if type(index) is not int or index < 0 or index >= len(self.pages) or self.pages[index].is_closed():
            raise ValueError("Unknown or closed page")
        return self.pages[index]

    @staticmethod
    async def active_dialog(frame):
        dialogs = frame.locator("dialog[open], [role=dialog][aria-modal=true], [role=alertdialog][aria-modal=true]")
        for index in range(await dialogs.count() - 1, -1, -1):
            candidate = dialogs.nth(index)
            if await candidate.is_visible():
                return candidate
        return None

    async def observe(self, page_index: int, frame_index=0, offset=0, control_offset=0):
        page = self.page(page_index)
        if min(frame_index, offset, control_offset) < 0 or frame_index >= len(page.frames):
            raise ValueError("Invalid observation offset or frame")
        frame = page.frames[frame_index]
        self.known_urls.add(frame.url)
        text = await frame.locator("body").inner_text(timeout=8000)
        self.generation += 1
        generation = self.generation  # Reserve before awaits in concurrent observations.
        # Observing one frame does not invalidate refs on unrelated tabs/frames.
        self.controls = {ref: selected for ref, selected in self.controls.items()
                         if selected[:2] != (page_index, frame_index)}
        controls = []
        control_selector = "a, button, input, textarea, select, [role=button], [role=tab], [role=checkbox]"
        active_dialog = await self.active_dialog(frame)
        locator = active_dialog.locator(control_selector) if active_dialog else frame.locator(control_selector)
        total = await locator.count()
        for index in range(control_offset, min(total, control_offset + 100)):
            item = locator.nth(index)
            if not await item.is_visible():
                continue
            handle = await item.element_handle()
            info = await handle.evaluate("""e => ({tag: e.tagName, type: e.getAttribute('type'),
                text: (e.innerText || e.textContent || '').slice(0, 500),
                label: e.getAttribute('aria-label') || (e.labels ? [...e.labels].map(x => x.innerText).join(' ') : ''),
                placeholder: e.getAttribute('placeholder'), name: e.getAttribute('name'),
                value: e.tagName === 'INPUT' && e.type !== 'password' ? e.value.slice(0, 300) : undefined,
                hasValue: e.tagName === 'INPUT' && e.type === 'password' ? !!e.value : undefined,
                disabled: !!e.disabled, checked: e.checked, min: e.min, max: e.max, step: e.step,
                href: e.getAttribute('href'), options: e.tagName === 'SELECT' ?
                [...e.options].map(x => ({value: x.value, text: x.text})) : undefined})""")
            ref = f"control-{generation}-{index}"
            self.controls[ref] = (page_index, frame_index, handle)
            self.control_info[ref] = info
            if info.get("href"):
                self.known_urls.add(urljoin(frame.url, info["href"]))
            controls.append({"ref": ref, **info})
        excerpt = text[offset:offset + 16000]
        # inner_text excludes input/select values. Preserve observed form facts as
        # evidence too (e.g. the portal's tender reference), never password values.
        evidence_text = excerpt + "\nVisible controls:\n" + json.dumps(controls, ensure_ascii=False)
        observation = self.book.observe(frame.url, evidence_text)
        self.observed_pages[observation] = page_index
        self.control_info = {ref: info for ref, info in self.control_info.items() if ref in self.controls}
        return {"observation_id": observation, "page": page_index, "browser": self.browser_index(page), "url": frame.url, "text": excerpt,
                "active_dialog": (await active_dialog.inner_text())[:2000] if active_dialog else None,
                "text_length": len(text), "offset": offset, "controls": controls, "control_count": total,
                "frames": [{"frame": i, "url": f.url, "name": f.name} for i, f in enumerate(page.frames)],
                "pages": self.page_list()}

    async def act(self, operation: str, page: int | None = None, **args):
        if operation in {"click", "fill", "select", "press", "download", "set_range"} and not args.get("ref"):
            raise ValueError(f"{operation} requires a ref from the latest observation, not a URL or selector")
        if operation in {"fill", "select", "press", "set_range"} and "value" not in args:
            raise ValueError(f"{operation} requires value (press uses a keyboard key such as Enter)")
        if operation == "pages":
            return self.page_list()
        if operation == "new_tab":
            browser_index = args.get("browser", 0)
            if type(browser_index) is not int or not 0 <= browser_index < len(self.browsers):
                raise ValueError("Unknown browser")
            for row in self.page_list():
                if row["browser"] == browser_index and row["url"] == "about:blank":
                    self.active_pages[browser_index] = row["page"]
                    await self.page(row["page"]).bring_to_front()
                    return {"page": row["page"], "browser": browser_index, "reused_blank": True,
                            "pages": self.page_list(), "next": "Navigate this existing blank tab to the selected site"}
            new = await self.browsers[browser_index].contexts[0].new_page()
            self.page_list()
            self.active_pages[browser_index] = self.pages.index(new)
            return {"page": self.pages.index(new), "pages": self.page_list(),
                    "next": "Navigate the new tab to a run-provided site URL"}
        if operation == "new_context":
            browser_index = args.get("browser", 0)
            if type(browser_index) is not int or not 0 <= browser_index < len(self.browsers):
                raise ValueError("Unknown browser")
            context = await self.browsers[browser_index].new_context()
            context.set_default_timeout(8000)
            context.set_default_navigation_timeout(15000)
            await context.route("**/*", self._route)
            new = await context.new_page()
            self.page_list()
            return {"page": self.pages.index(new), "pages": self.page_list(),
                    "next": "Fresh browser context has no prior login; navigate to a run-provided site URL"}
        if page is None:
            # A ref identifies its own observed page. Most model calls omit the
            # optional page argument, particularly after opening a new tab.
            ref = args.get("ref")
            if operation == "fill_fields" and isinstance(args.get("fields"), list) and args["fields"]:
                ref = args["fields"][0].get("ref") if isinstance(args["fields"][0], dict) else None
            page = (self.controls[ref][0] if ref in self.controls else
                    self.preferred_page(args["browser"]) if "browser" in args else self.preferred_page(0))
        target = self.page(page)
        if operation != "screenshot":
            self.active_pages[self.browser_index(target)] = page
            await target.bring_to_front()
        if operation in {"click", "fill", "fill_fields", "select", "press", "set_range"}:
            refs = [f.get("ref") for f in args.get("fields", [])] if operation == "fill_fields" else [args.get("ref")]
            relevant_frames = {target.main_frame}
            for ref in refs:
                selected = self.controls.get(ref)
                if selected and selected[0] == page and selected[1] < len(target.frames):
                    ancestor = target.frames[selected[1]]
                    while ancestor is not None:
                        relevant_frames.add(ancestor)
                        ancestor = ancestor.parent_frame
            for frame_index, frame in enumerate(target.frames):
                if frame not in relevant_frames:
                    continue
                dialog = await self.active_dialog(frame)
                if dialog is None:
                    continue
                for ref in refs:
                    selected = self.controls.get(ref)
                    inside = (selected is not None and selected[:2] == (page, frame_index)
                              and await dialog.evaluate("(dialog, element) => dialog.contains(element)", selected[2]))
                    if not inside:
                        # A late overlay invalidates the planned action, not the task.
                        # Return fresh evidence; never infer which control dismisses it.
                        observed = await self.observe(page, frame_index)
                        observed["interrupted_action"] = {"operation": operation, "executed": False,
                            "next": "A dialog now covers the planned control. Review its purpose and observed controls, choose how to proceed, then resume your task."}
                        return observed
        if operation == "extract":
            frame_index = args.get("frame", 0)
            if not 0 <= frame_index < len(target.frames):
                raise ValueError("Invalid frame")
            frame = target.frames[frame_index]
            # Extract only the model-selected, already reached page. Never follow links.
            tables = await frame.locator("table").evaluate_all("""tables => tables.map(t =>
                [...t.rows].map(r => [...r.cells].map(c => c.innerText)))""")
            text = json.dumps(tables, ensure_ascii=False)
            observation = self.book.observe(frame.url, text)
            self.observed_pages[observation] = page
            return {"observation_id": observation, "page": page, "browser": self.browser_index(target), "url": frame.url, "tables": tables,
                    "next": "Cite cells from this observation; select relevant records using the model."}
        if operation == "observe":
            return await self.observe(page, args.get("frame", 0), args.get("offset", 0), args.get("control_offset", 0))
        if operation == "screenshot":
            return {"image_url": "data:image/png;base64," + base64.b64encode(await target.screenshot()).decode()}
        if operation in {"read_download", "parse_download"}:
            record = self.downloads[args["download_id"]]
            text = document_text(record["bytes"], record["name"], args.get("member"))
            offset = args.get("offset", 0)
            if offset < 0:
                raise ValueError("Negative offset")
            if operation == "parse_download":
                name = args.get("member") or record["name"]
                if name.lower().endswith(".csv"):
                    dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
                    rows = list(csv.reader(io.StringIO(text), dialect))
                    data = {"columns": rows[0] if rows else [], "rows": rows[1 + offset:101 + offset],
                            "row_count": max(0, len(rows) - 1), "offset": offset}
                elif name.lower().endswith(".json"):
                    data = json.loads(text)
                else:
                    raise ValueError("Structured parsing supports selected CSV/JSON; use read_download for PDF/text or select a ZIP member")
                encoded = json.dumps(data, ensure_ascii=False)
                if len(encoded) > 24000:
                    raise ValueError("Structured result too large; use read_download with offsets")
                observation = self.book.observe(record["url"] + "#" + str(args.get("member", "")), encoded)
                return {"observation_id": observation, "data": data}
            excerpt = text[offset:offset + 24000]
            observation = self.book.observe(record["url"] + "#" + str(args.get("member", "")), excerpt)
            return {"observation_id": observation, "text": excerpt, "text_length": len(text), "offset": offset}
        try:
            next_frame = 0
            mutation_started = False
            async def require_fillable(handle):
                kind = await handle.evaluate("e => e.tagName === 'TEXTAREA' ? 'textarea' : e.tagName === 'INPUT' ? e.type : e.tagName.toLowerCase()")
                if kind not in {"textarea", "text", "search", "email", "password", "number", "tel", "url",
                                "date", "datetime-local", "month", "week", "time"}:
                    alternative = ("press ArrowLeft/ArrowRight on its ref" if kind == "range" else
                                   "click it or use select for a dropdown")
                    raise ValueError(f"{kind} control cannot be filled; {alternative}")
            if operation == "navigate":
                if origin(args["url"]) not in self.origins:
                    raise ValueError("Navigation target is outside challenge sites")
                if args["url"] not in self.known_urls:
                    raise ValueError("Use a run-provided or observed URL; discover targets through page controls")
                browser_index = self.browser_index(target)
                destination = origin(args["url"])
                assigned = self.browser_origins.get(browser_index)
                if len(self.browsers) == 4 and assigned is not None and assigned != destination:
                    raise ValueError("Keep sites independently visible: this browser already belongs to " + assigned +
                                     ". Use pages and select another browser for " + destination)
                self.browser_origins[browser_index] = destination
                mutation_started = True
                await target.goto(args["url"], wait_until="commit")
            elif operation == "scroll":
                mutation_started = True
                await target.mouse.wheel(0, max(-800, min(800, args.get("pixels", 600))))
            elif operation == "fill_fields":
                fields = args["fields"]
                if not isinstance(fields, list) or not 1 <= len(fields) <= 12:
                    raise ValueError("Select between one and twelve observed fields")
                selected = []
                for field in fields:
                    if not isinstance(field, dict) or set(field) != {"ref", "value"} or not isinstance(field["value"], str):
                        raise ValueError("Each field needs an observed ref and string value")
                    if field["ref"] not in self.controls:
                        raise ValueError("Control ref expired; observe the page and use its new refs")
                    control_page, frame_index, handle = self.controls[field["ref"]]
                    if control_page != page:
                        raise ValueError("All fields must belong to the selected page")
                    if selected and selected[0][0] != frame_index:
                        raise ValueError("All fields must belong to one observed frame")
                    selected.append((frame_index, handle, field["value"]))
                next_frame = selected[0][0]
                for _, handle, _ in selected:
                    await require_fillable(handle)
                mutation_started = True
                for _, handle, value in selected:
                    await handle.fill(value)
            elif operation in {"click", "fill", "select", "press", "download", "set_range"}:
                if args["ref"] not in self.controls:
                    raise ValueError("Control ref expired; observe the page and use its new refs")
                control_page, next_frame, handle = self.controls[args["ref"]]
                if control_page != page:
                    raise ValueError("Control belongs to another page")
                if operation == "click":
                    mutation_started = True
                    await handle.click()
                elif operation == "fill":
                    await require_fillable(handle)
                    mutation_started = True
                    await handle.fill(args["value"])
                elif operation == "select":
                    mutation_started = True
                    await handle.select_option(value=args["value"])
                elif operation == "press":
                    mutation_started = True
                    await handle.press(args["value"])
                elif operation == "set_range":
                    settings = await handle.evaluate("""e => e.tagName === 'INPUT' && e.type === 'range' ?
                        {min: Number(e.min || 0), max: Number(e.max || 100), value: Number(e.value),
                         step: e.step === 'any' ? null : Number(e.step || 1),
                         direction: getComputedStyle(e).direction} : null""")
                    if settings is None:
                        raise ValueError("set_range requires an observed input[type=range] ref")
                    desired = float(args["value"])
                    low, high = settings["min"], settings["max"]
                    if not math.isfinite(desired) or not low <= desired <= high or high <= low:
                        raise ValueError("Range value must be finite and within the observed min/max")
                    box = await handle.bounding_box()
                    if box is None or box["width"] < 16:
                        raise ValueError("Range control has no usable horizontal bounding box")
                    usable = box["width"] - 16
                    def x_for(value):
                        ratio = (value - low) / (high - low)
                        if settings["direction"] == "rtl":
                            ratio = 1 - ratio
                        return box["x"] + 8 + usable * ratio
                    y = box["y"] + box["height"] / 2
                    mutation_started = True
                    step = settings["step"]
                    count = round((desired - low) / step) if step else None
                    if desired == high:
                        await handle.press("End")
                    elif desired == low:
                        await handle.press("Home")
                    elif count is not None and count <= 200 and math.isclose(low + count * step, desired):
                        await handle.press("Home")
                        for _ in range(count):
                            await handle.press("ArrowLeft" if settings["direction"] == "rtl" else "ArrowRight")
                    else:
                        await target.mouse.move(x_for(settings["value"]), y)
                        await target.mouse.down()
                        try:
                            await target.mouse.move(x_for(desired), y, steps=12)
                        finally:
                            await target.mouse.up()
                    actual = float(await handle.input_value())
                    if not math.isclose(actual, desired, rel_tol=0, abs_tol=(high - low) / 200):
                        raise ValueError(f"Range moved to {actual}; observe its value before continuing")
                else:
                    mutation_started = True
                    async with target.expect_download(timeout=15000) as pending:
                        await handle.click()
                    download = await pending.value
                    path = await download.path()
                    if path is None or Path(path).stat().st_size > MAX_DOCUMENT:
                        raise ValueError("Missing or oversized download")
                    key = f"download-{len(self.downloads) + 1}"
                    self.downloads[key] = {"bytes": Path(path).read_bytes(), "name": download.suggested_filename,
                                           "url": download.url}
                    return {"download_id": key, "name": download.suggested_filename}
            else:
                raise ValueError("Unknown browser operation")
        finally:
            # A timed-out action may still have changed this page. Never reuse its controls.
            if mutation_started:
                self.controls = {ref: selected for ref, selected in self.controls.items()
                                 if selected[0] != page}
        # The model chose this page and action. Read only that page after the action so
        # the next control decision needs no extra model/tool round trip.
        try:
            observation = await self.observe(page, next_frame if next_frame < len(target.frames) else 0)
        except Exception as exc:
            return {"status": "action_completed", "pages": self.page_list(),
                    "observation_error": type(exc).__name__,
                    "next": "Action may have succeeded; observe the page before acting again"}
        return {"status": "action_completed", **observation}
