"""Bounded browser actions selected by the model; connects only to supplied CDP browsers."""
from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from .evidence import EvidenceBook

MAX_DOCUMENT = 20 * 1024 * 1024


def origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected an HTTP(S) URL without embedded credentials")
    return f"{parts.scheme}://{parts.netloc.lower()}"


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
        return [{"page": i, "url": p.url} for i, p in enumerate(self.pages) if not p.is_closed()]

    def page(self, index):
        self.page_list()
        if type(index) is not int or index < 0 or index >= len(self.pages) or self.pages[index].is_closed():
            raise ValueError("Unknown or closed page")
        return self.pages[index]

    async def observe(self, page_index: int, frame_index=0, offset=0, control_offset=0):
        page = self.page(page_index)
        if min(frame_index, offset, control_offset) < 0 or frame_index >= len(page.frames):
            raise ValueError("Invalid observation offset or frame")
        frame = page.frames[frame_index]
        text = await frame.locator("body").inner_text(timeout=8000)
        self.generation += 1
        self.controls.clear()
        controls = []
        locator = frame.locator("a, button, input, textarea, select, [role=button], [role=tab], [role=checkbox]")
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
                href: e.getAttribute('href'), options: e.tagName === 'SELECT' ?
                [...e.options].map(x => ({value: x.value, text: x.text})) : undefined})""")
            ref = f"control-{self.generation}-{index}"
            self.controls[ref] = (page_index, handle)
            controls.append({"ref": ref, **info})
        excerpt = text[offset:offset + 16000]
        observation = self.book.observe(frame.url, excerpt)
        self.observed_pages[observation] = page_index
        return {"observation_id": observation, "page": page_index, "url": frame.url, "text": excerpt,
                "text_length": len(text), "offset": offset, "controls": controls, "control_count": total,
                "frames": [{"frame": i, "url": f.url, "name": f.name} for i, f in enumerate(page.frames)],
                "pages": self.page_list()}

    async def act(self, operation: str, page: int = 0, **args):
        if operation == "pages":
            return self.page_list()
        if operation == "new_tab":
            browser_index = args.get("browser", 0)
            if type(browser_index) is not int or not 0 <= browser_index < len(self.browsers):
                raise ValueError("Unknown browser")
            new = await self.browsers[browser_index].contexts[0].new_page()
            self.page_list()
            return {"page": self.pages.index(new)}
        target = self.page(page)
        if operation == "observe":
            return await self.observe(page, args.get("frame", 0), args.get("offset", 0), args.get("control_offset", 0))
        if operation == "screenshot":
            return {"image_url": "data:image/png;base64," + base64.b64encode(await target.screenshot()).decode()}
        if operation == "read_download":
            record = self.downloads[args["download_id"]]
            text = document_text(record["bytes"], record["name"], args.get("member"))
            offset = args.get("offset", 0)
            if offset < 0:
                raise ValueError("Negative offset")
            excerpt = text[offset:offset + 24000]
            observation = self.book.observe(record["url"] + "#" + str(args.get("member", "")), excerpt)
            return {"observation_id": observation, "text": excerpt, "text_length": len(text), "offset": offset}
        try:
            if operation == "navigate":
                if origin(args["url"]) not in self.origins:
                    raise ValueError("Navigation target is outside challenge sites")
                await target.goto(args["url"], wait_until="domcontentloaded")
            elif operation == "scroll":
                await target.mouse.wheel(0, max(-800, min(800, args.get("pixels", 600))))
            elif operation in {"click", "fill", "select", "press", "download"}:
                control_page, handle = self.controls[args["ref"]]
                if control_page != page:
                    raise ValueError("Control belongs to another page")
                if operation == "click":
                    await handle.click()
                elif operation == "fill":
                    await handle.fill(args["value"])
                elif operation == "select":
                    await handle.select_option(value=args["value"])
                elif operation == "press":
                    await handle.press(args["value"])
                else:
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
            # A timed-out action may still have changed the page. Never reuse its controls.
            self.controls.clear()
        return {"status": "action_completed", "pages": self.page_list(), "next": "observe before using controls"}
