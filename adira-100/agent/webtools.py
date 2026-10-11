"""Browser tools for the model: a compact text snapshot of the page with numbered refs for every interactive element,
and actions on those refs. Generic: nothing here knows about any particular website."""
import asyncio
import base64
import time
import io
import re
import zipfile

SNAPSHOT_JS = r"""
(startRef) => {
  let ref = startRef;
  const out = [];
  const INTERACTIVE = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],[onclick],summary,[tabindex]:not([tabindex="-1"])';
  const visible = (el) => {
    const st = el.ownerDocument.defaultView.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const label = (el) => {
    let t = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || el.getAttribute('placeholder') || el.getAttribute('alt') || el.getAttribute('name') || '').trim();
    return t.replace(/\s+/g, ' ').slice(0, 80);
  };
  const walk = (node, depth) => {
    if (node.nodeType === 3) {
      const t = node.textContent.replace(/\s+/g, ' ').trim();
      if (t) out.push(t);
      return;
    }
    if (node.nodeType !== 1) return;
    const el = node;
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'noscript', 'template', 'svg', 'head'].includes(tag)) return;
    if (!visible(el) && tag !== 'option') {
      // hidden containers may still hold visible fixed children rarely; skip for compactness
      return;
    }
    if (tag === 'iframe' || tag === 'frame') {
      try {
        const doc = el.contentDocument;
        if (doc && doc.body) { out.push('\n[iframe ' + (el.getAttribute('title') || el.getAttribute('src') || '') + ']\n'); walk(doc.body, depth + 1); out.push('\n[/iframe]\n'); }
        else out.push('[iframe src=' + el.getAttribute('src') + ' (cross-origin; open its src)]');
      } catch (e) { out.push('[iframe src=' + el.getAttribute('src') + ' (cross-origin; open its src)]'); }
      return;
    }
    const isInteractive = el.matches(INTERACTIVE) && !el.disabled;
    if (isInteractive) {
      ref += 1;
      el.setAttribute('data-aref', String(ref));
      let desc = tag;
      if (tag === 'input') {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (type === 'hidden') return;
        desc = 'input:' + type;
        const nm = el.getAttribute('name') || el.id || '';
        let lab = '';
        if (el.id) { const l = el.ownerDocument.querySelector('label[for="' + el.id + '"]'); if (l) lab = l.innerText.trim(); }
        const ph = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
        if (type === 'checkbox' || type === 'radio') {
          out.push(`[${ref}] ${desc}${el.checked ? ' (checked)' : ''} ${lab || nm} ${el.value && el.value !== 'on' ? 'value=' + el.value : ''}`);
        } else {
          out.push(`[${ref}] ${desc} ${lab ? '"' + lab + '"' : ''} name=${nm} ${ph ? 'hint="' + ph + '"' : ''} value="${(el.value || '').slice(0, 60)}"`);
        }
        return;
      }
      if (tag === 'select') {
        const opts = Array.from(el.options).map(o => (o.selected ? '*' : '') + o.text.trim() + (o.value !== o.text.trim() ? '=' + o.value : '')).slice(0, 40).join(' | ');
        out.push(`[${ref}] select name=${el.getAttribute('name') || el.id || ''} options: ${opts}`);
        return;
      }
      if (tag === 'textarea') {
        out.push(`[${ref}] textarea name=${el.getAttribute('name') || ''} value="${(el.value || '').slice(0, 80)}"`);
        return;
      }
      const href = tag === 'a' ? (el.getAttribute('href') || '') : '';
      const hrefShort = href && !href.startsWith('javascript') && href !== '#' ? ' -> ' + href.slice(0, 100) : '';
      out.push(`[${ref}] ${tag === 'a' ? 'link' : tag === 'button' ? 'button' : (el.getAttribute('role') || tag)} "${label(el)}"${hrefShort}`);
      // do not descend: label already covers text (but descend if it contains inputs)
      if (!el.querySelector('input,select,textarea,button,a')) return;
    }
    const block = /^(div|p|h[1-6]|li|tr|table|section|article|header|footer|form|ul|ol|dl|dt|dd|br|hr|fieldset|legend|pre|main|nav|aside|dialog|details|blockquote)$/.test(tag);
    if (/^h[1-6]$/.test(tag)) out.push('\n' + '#'.repeat(parseInt(tag[1])) + ' ');
    else if (block) out.push('\n');
    if (tag === 'td' || tag === 'th') out.push(' | ');
    for (const c of el.childNodes) walk(c, depth + 1);
    if (block) out.push('\n');
  };
  walk(document.body, 0);
  let text = out.join(' ').replace(/[\u200b-\u200f\u2060\ufeff\u00ad]/g, '').replace(/[ \t]+/g, ' ').replace(/ ?\n ?/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  return {text, ref};
}
"""


SPARE_BROWSERS: list = []  # the run's browsers, set by the agent, used when one stops loading pages


class Browser:
    """One tab the model drives. Keeps the last dialog message, downloads and the ref counter."""

    def __init__(self, page, name="browser"):
        self.page = page
        self.name = name
        self.events: list[str] = []
        self.ref = 0
        self.downloads: list[str] = []
        self._attach(page)

    def _attach(self, page):
        page.on("dialog", self._on_dialog)
        page.on("download", lambda d: asyncio.ensure_future(self._on_download(d)))
        page.context.on("page", self._on_popup)

    async def _on_dialog(self, dialog):
        self.events.append(f"Browser dialog ({dialog.type}): {dialog.message!r} -> accepted")
        try:
            await dialog.accept()
        except Exception:
            pass

    def _on_popup(self, page):
        asyncio.ensure_future(self._maybe_switch(page))

    async def _maybe_switch(self, page):
        try:
            opener = await page.opener()
        except Exception:
            opener = None
        if opener is not self.page:
            return
        self.events.append("A new tab opened; switched to it (use back_to_previous_tab to return).")
        self.previous = self.page
        self.page = page
        page.on("dialog", self._on_dialog)
        page.on("download", lambda d: asyncio.ensure_future(self._on_download(d)))

    async def _on_download(self, download):
        try:
            path = await download.path()
            data = open(path, "rb").read()
            text = extract_file_text(download.suggested_filename, data)
            self.downloads.append(f"=== Downloaded {download.suggested_filename} ===\n{text}")
            self.events.append(f"Downloaded {download.suggested_filename}; its content is shown below.")
        except Exception as e:
            self.events.append(f"Download failed: {e}")

    async def snapshot(self, max_chars=30000) -> str:
        page = self.page
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await self._recover_blank()
        page = self.page
        try:  # close floating popups (surveys, notices) via their own close control before the model looks
            await asyncio.wait_for(self.close_popups(), 5)
        except Exception:
            pass
        await asyncio.sleep(0.3)
        parts = []
        self.ref = 0
        frames = [page.main_frame]
        try:
            res = await page.main_frame.evaluate(SNAPSHOT_JS, self.ref)
            self.ref = res["ref"]
            parts.append(res["text"])
        except Exception as e:
            parts.append(f"(page not readable: {e})")
        # cross-origin frames: read them separately
        for fr in page.frames:
            if fr is page.main_frame:
                continue
            try:
                same = await fr.evaluate("() => { try { return !!window.parent.document; } catch(e) { return false; } }")
            except Exception:
                continue
            if same:
                continue
            try:
                res = await fr.evaluate(SNAPSHOT_JS, self.ref)
                self.ref = res["ref"]
                parts.append(f"\n[frame {fr.url}]\n{res['text']}\n[/frame]")
            except Exception:
                pass
        head = f"URL: {page.url}\nTitle: {await safe_title(page)}\n"
        if self.events:
            head += "Events: " + " | ".join(self.events[-6:]) + "\n"
            self.events.clear()
        body = "\n".join(parts)
        if self.downloads:
            body += "\n\n" + "\n\n".join(self.downloads)
            self.downloads.clear()
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n...(truncated, {len(body) - max_chars} more chars; use find_text or scroll the result set)"
        return head + "\n" + body

    async def _locate(self, ref: int):
        for fr in self.page.frames:
            loc = fr.locator(f'[data-aref="{ref}"]')
            try:
                if await loc.count():
                    return loc.first
            except Exception:
                continue
        raise ValueError(f"No element [{ref}] on the current page; take a new snapshot (refs change after every action).")

    async def click(self, ref: int):
        loc = await self._locate(ref)
        url_before = self.page.url
        is_submit = await loc.evaluate("el => el.tagName === 'BUTTON' || el.type === 'submit' || el.type === 'button'")
        try:
            await loc.click(timeout=5000)
        except Exception as e:
            if "intercepts pointer events" in str(e) and await self.close_popups():
                try:
                    await loc.click(timeout=5000)
                except Exception:
                    await loc.click(timeout=5000, force=True)
            else:
                await loc.click(timeout=5000, force=True)
        await self._settle()
        await asyncio.sleep(0.3)
        if is_submit and self.page.url.split("?")[0] == url_before.split("?")[0]:
            await self._hint_unchecked()

    async def _hint_unchecked(self):
        """After a button click that stayed on the same page: list unticked checkboxes (a common reason a form
        does not advance)."""
        try:
            boxes = await self.page.evaluate("""() => Array.from(document.querySelectorAll('input[type=checkbox]'))
                .filter(b => !b.checked && b.offsetParent !== null)
                .map(b => { const l = (b.closest('label') || {}).innerText || (b.labels && b.labels[0] ? b.labels[0].innerText : '') || b.name;
                            return (l || '').trim().slice(0, 60); })""")
        except Exception:
            return
        if boxes:
            self.events.append("Still on the same page after the click. Unticked checkboxes here: " +
                               "; ".join(f"'{b}'" for b in boxes) + ". If the form did not advance, tick the "
                               "required ones (not your own terms/AGB) and submit again.")

    async def close_popups(self) -> int:
        """Close visible popups/overlays via their own close control (×, Schließen, Close), never via their links."""
        n = await self.page.evaluate(CLOSE_POPUPS_JS)
        if n:
            self.events.append(f"Closed {n} popup(s) (survey or notice).")
            await asyncio.sleep(0.3)
        return n

    async def fill(self, ref: int, text: str, submit: bool = False):
        loc = await self._locate(ref)
        if (await loc.get_attribute("type") or "").lower() == "range":
            await self.drag_slider(ref)
            return
        await loc.fill(str(text), timeout=5000)
        if submit:
            await loc.press("Enter")
        await self._settle()

    async def select(self, ref: int, option: str):
        loc = await self._locate(ref)
        try:
            await loc.select_option(label=option, timeout=3000)
        except Exception:
            await loc.select_option(value=option, timeout=3000)
        await self._settle()

    async def drag_slider(self, ref: int):
        """Drag a range slider all the way to the right, like a person would."""
        loc = await self._locate(ref)
        box = await loc.bounding_box()
        if box:
            y = box["y"] + box["height"] / 2
            await self.page.mouse.move(box["x"] + 2, y)
            await self.page.mouse.down()
            for i in range(1, 11):
                await self.page.mouse.move(box["x"] + box["width"] * i / 10 + 2, y)
                await asyncio.sleep(0.03)
            await self.page.mouse.up()
        await loc.evaluate("""el => { if (el.value !== el.max) { el.value = el.max;
            el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); } }""")
        await self._settle()

    async def fill_form(self, fields: list, apply_button: str = "") -> str:
        """Fill several form fields in order, in one step. Each field is {"field": name or label, "value": ...}.
        Dropdowns that depend on earlier choices are handled: after each dropdown choice the optional apply button
        (by its text) is clicked and the next dropdown's options are awaited. The model chooses fields and values."""
        done = []
        for f in fields:
            key, value = str(f.get("field", "")).strip(), str(f.get("value", "")).strip()
            loc = await self._field(key)
            if loc is None:
                done.append(f"{key}: NOT FOUND")
                continue
            tag = await loc.evaluate("el => el.tagName.toLowerCase() + ':' + (el.type || '')")
            try:
                if tag.startswith("select"):
                    option = None
                    for i in range(10):  # dependent dropdowns fill in after the previous choice is applied
                        loc = await self._field(key) or loc  # it may have been re-rendered
                        option = await loc.evaluate(MATCH_OPTION_JS, value)
                        if option is not None:
                            break
                        n_real = await loc.evaluate("el => Array.from(el.options).filter(o => o.value !== '' && "
                                                    "!o.disabled).length")
                        if n_real > 0 and i >= 2:  # options are there, none matches: stop waiting
                            break
                        await asyncio.sleep(0.4)
                    if option is None:
                        real = await loc.evaluate("el => Array.from(el.options).filter(o => o.value !== '' && "
                                                  "!o.disabled).map(o => [o.value, o.text.trim()])")
                        if len(real) == 1:  # a dependent dropdown with a single choice: take it
                            option = real[0][0]
                            done.append(f"{key}: only option {real[0][1]!r} taken (wanted {value!r})")
                        else:
                            opts = " | ".join(t for _, t in real)
                            done.append(f"{key}: NO option like {value!r}; offered: {opts[:300]} -> choose one "
                                        "of these and fill the remaining fields")
                            break  # later dependent fields cannot be filled before this one
                    await loc.select_option(value=option, timeout=3000)
                    await self._settle()
                    if apply_button:
                        await self._click_text(apply_button)
                    done.append(f"{key} = {value}")
                elif tag.endswith(":checkbox") or tag.endswith(":radio"):
                    await loc.set_checked(value.lower() not in ("false", "0", "no", "nein", ""), timeout=3000, force=True)
                    done.append(f"{key} = {value}")
                else:
                    await loc.fill(value, timeout=3000)
                    done.append(f"{key} = {value}")
            except Exception as e:
                done.append(f"{key}: failed ({str(e)[:80]})")
        await self._settle()
        return "fill_form: " + "; ".join(done)

    async def _field(self, key: str):
        """A form control by its name/id, its label text, aria-label or placeholder, in any frame."""
        async def visible(loc):
            try:
                for i in range(await loc.count()):  # pages hide decoy fields with the same name: take a visible one
                    if await loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:
                pass
            return None
        for fr in self.page.frames:
            for sel in (f'[name="{key}"]', f'[id="{key}"]', f'[aria-label="{key}"]', f'[placeholder="{key}"]'):
                found = await visible(fr.locator(sel))
                if found is not None:
                    return found
            try:
                found = await visible(fr.get_by_label(key, exact=False))
                if found is not None:
                    return found
            except Exception:
                pass
        return None

    async def _click_text(self, text: str):
        for fr in self.page.frames:
            try:
                loc = fr.get_by_role("button", name=text)
                if await loc.count():
                    await loc.first.click(timeout=3000)
                    await self._settle()
                    return True
            except Exception:
                pass
        return False

    async def back_to_previous_tab(self):
        prev = getattr(self, "previous", None)
        if prev and not prev.is_closed():
            self.page = prev

    async def check(self, ref: int, checked: bool = True):
        loc = await self._locate(ref)
        await loc.set_checked(checked, timeout=5000, force=True)
        await self._settle()

    async def press(self, key: str):
        await self.page.keyboard.press(key)
        await self._settle()

    async def goto(self, url: str):
        await self.load_until_ready(url)

    async def load_until_ready(self, url: str, budget: float = 120) -> bool:
        """Open `url` and keep reloading until the page really shows content; after repeated failures continue in a
        fresh session of another browser. Raises if nothing loads within the budget."""
        t_end = time.time() + budget
        attempt, last = 0, None
        while time.time() < t_end:
            attempt += 1
            try:
                if attempt == 1 or not self.page.url.startswith("http"):
                    resp = await self.page.goto(url, timeout=20000, wait_until="domcontentloaded")
                else:
                    resp = await self.page.reload(timeout=20000, wait_until="domcontentloaded")
                if resp is not None and 400 <= resp.status < 500:
                    # the server answered: the address does not exist (or is not allowed) - no reload, no failover
                    raise ValueError(f"HTTP {resp.status}: this address does not exist on the website. Do not "
                                     "guess URLs; use a link or button you saw on the page.")
                text = await self.page.evaluate("() => (document.body && document.body.innerText || '').trim().length")
                if text > 0:
                    await self._settle()
                    return True
                last = "empty page"
            except ValueError:
                raise
            except Exception as e:
                last = str(e)[:120]
            if attempt % 3 == 0:  # this browser keeps failing: move to another one and start over there
                if await self.move_to_spare_browser():
                    attempt = 0
            await asyncio.sleep(2)
        raise TimeoutError(f"{url} did not load within {budget:.0f}s ({last})")

    async def _recover_blank(self):
        """A page that turned blank mid-session (white page, crashed renderer): reload it, else another browser."""
        try:
            n = await asyncio.wait_for(self.page.evaluate(
                "() => (document.body && document.body.innerText || '').trim().length"), 8)
        except Exception:
            n = 0
        url = self.page.url
        if n > 0 or not url.startswith("http"):
            return
        try:
            await self.load_until_ready(url, budget=45)
            self.events.append("The page was blank and has been reloaded.")
        except Exception as e:
            self.events.append(f"The page stayed blank ({str(e)[:80]}).")

    async def move_to_spare_browser(self) -> bool:
        """A browser that stopped loading pages: continue in a fresh session of another of the run's browsers."""
        current = self.page.context.browser
        for b in SPARE_BROWSERS:
            if b is current:
                continue
            try:
                ctx = await b.new_context(viewport={"width": 1280, "height": 800}, accept_downloads=True)
                self.page = await ctx.new_page()
                self._attach(self.page)
                self.events.append("This browser stopped loading pages; continuing in a fresh session in another "
                                   "browser (you may need to log in again).")
                return True
            except Exception:
                continue
        return False

    async def back(self):
        await self.page.go_back(timeout=15000)
        await self._settle()

    async def _settle(self):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.4)

    async def read_page(self) -> str:
        """Full text of the current page and all its frames, including collapsed/hidden sections."""
        parts = []
        for fr in self.page.frames:
            try:
                parts.append(f"[frame {fr.url}]\n" + extract_file_text("page.html", (await fr.content()).encode(), "html"))
            except Exception:
                pass
        return f"URL: {self.page.url}\n" + "\n".join(parts)

    async def find_text(self, query: str, context: int = 300) -> str:
        snap = await self.snapshot(max_chars=10**7)
        hits = [m.start() for m in re.finditer(re.escape(query), snap, re.IGNORECASE)]
        if not hits:
            return f"'{query}' not found on the page."
        return "\n---\n".join(snap[max(0, h - context): h + context] for h in hits[:8])

    async def fetch_text(self, url: str) -> str:
        """Fetch a document URL from inside the page (same cookies, same network path as the browser) and return its
        text. ZIPs and PDFs are unpacked."""
        full = url if "://" in url else _join(self.page.url, url)
        try:
            res = await self.page.evaluate(FETCH_JS, full)
            data = base64.b64decode(res["b64"])
            status, ctype = res["status"], res["ctype"]
        except Exception:
            resp = await self.page.context.request.get(full, timeout=30000)
            data, status, ctype = await resp.body(), resp.status, resp.headers.get("content-type", "")
        name = full.split("?")[0].rsplit("/", 1)[-1]
        if status == 404:
            return (f"HTTP 404 {url}: this address does not exist. Do not guess URLs; use a link or button you saw "
                    "on the page.")
        return f"HTTP {status} {url}\n" + extract_file_text(name, data, ctype)


MATCH_OPTION_JS = """(el, want) => {
  const norm = (x) => (x || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  let w = norm(want);
  if (/^(keine?|ohne|none|no|n\\/a|-)(\\b| )/.test(w) || /keine.*gefordert|nicht gefordert/.test(w)) w = '__none__';
  if (w === '__none__') {
    const o = Array.from(el.options).find(o => o.value !== '' && /ohne|keine|none|no certification/i.test(o.text + ' ' + o.value));
    return o ? o.value : null;
  }
  const opts = Array.from(el.options).filter(o => !o.disabled && o.value !== '');
  const by = (f) => { const o = opts.find(f); return o ? o.value : null; };
  return by(o => norm(o.text) === w) ?? by(o => norm(o.value) === w) ?? by(o => norm(o.text).startsWith(w + ' '))
      ?? by(o => norm(o.text).startsWith(w)) ?? by(o => norm(o.text).includes(w)) ?? null;
}"""


CLOSE_POPUPS_JS = """() => {
  const isClose = (el) => {
    const t = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '') + ' ' + (el.title || '')).trim();
    return /^(×|✕|x|schließen|close|ausblenden|später)$/i.test((el.innerText || '').trim()) || /schließen|close/i.test(el.getAttribute('aria-label') || '');
  };
  let n = 0;
  for (const el of document.querySelectorAll('button, [role=button]')) {
    if (el.tagName === 'A' || !isClose(el)) continue;
    const box = el.closest('dialog,[role=dialog],div,section,aside') || el;
    if (/cookie|einwillig|consent/i.test(box.innerText || '')) continue;  // consent needs an explicit choice
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    // only inside something that floats above the page (dialog, fixed/sticky/absolute overlay)
    let p = el, floating = false;
    while (p && p !== document.body) {
      const st = getComputedStyle(p);
      if (p.tagName === 'DIALOG' || p.getAttribute('role') === 'dialog' || ['fixed', 'sticky'].includes(st.position)) { floating = true; break; }
      p = p.parentElement;
    }
    if (floating) { el.click(); n++; }
  }
  return n;
}"""


FETCH_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  const b = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return {status: r.status, ctype: r.headers.get('content-type') || '', b64: btoa(s)};
}"""


def _join(base, rel):
    from urllib.parse import urljoin
    return urljoin(base, rel)


async def safe_title(page):
    try:
        return await page.title()
    except Exception:
        return ""


def extract_file_text(name: str, data: bytes, ctype: str = "") -> str:
    if name.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            return "\n\n".join(f"--- {n} ---\n" + extract_file_text(n, z.read(n)) for n in z.namelist() if not n.endswith("/"))
        except Exception as e:
            return f"(bad zip: {e})"
    if name.lower().endswith(".pdf") or data[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:
            return f"(pdf not readable: {e})"
    text = data.decode("utf-8", errors="replace")
    if "<html" in text[:2000].lower() or "html" in ctype:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text, flags=re.I)
        text = re.sub(r"</t[dh]>", " | ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as _h
        text = _h.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
    return ZW.sub("", text)[:60000]


ZW = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")
