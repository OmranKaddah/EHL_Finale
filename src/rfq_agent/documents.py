"""Bounded reading of documents and frames explicitly selected by the model."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

MAX_FILE_BYTES = 8 * 1024 * 1024


def parse_document(data: bytes, name: str) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("selected document exceeds the 8 MB reading limit")
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf':
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(data)).pages)
    if suffix in {'.txt', '.csv', '.md', '.json', '.xml', '.html', '.htm'}:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('cp1252')
        if suffix in {'.html', '.htm'}:
            from html.parser import HTMLParser
            class Text(HTMLParser):
                def __init__(self):
                    super().__init__(); self.parts = []; self.hidden = 0
                def handle_starttag(self, tag, attrs):
                    if tag in {'script', 'style'}: self.hidden += 1
                def handle_endtag(self, tag):
                    if tag in {'script', 'style'}: self.hidden = max(0, self.hidden - 1)
                def handle_data(self, value):
                    if not self.hidden: self.parts.append(value)
            parser = Text(); parser.feed(text)
            text = '\n'.join(parser.parts)
        return text
    raise ValueError("unsupported selected document format")


class InvestigationSession:
    def __init__(self, page, sites):
        self.page = page
        self.sites = sites
        self.frame = None
        self.document = None
        self.archive = None
        self.source_url = None
        self.offset = 0
        self.page_offset = 0
        # Set only by the submission owner; investigators keep every safety guard.
        self.authorize = None

    async def observe(self, site_id):
        from .planner import observe, MAX_PAGE_TEXT, _credential_values
        observation = await observe(self.frame or self.page, self.sites, site_id, self.page_offset)
        if self.document is not None:
            text = self.document[self.offset:self.offset + MAX_PAGE_TEXT]
            for site in self.sites:
                for secret in _credential_values(site).values():
                    text = text.replace(secret, '[redacted]') if secret else text
            observation.update(visible_text=text, url=self.source_url, title=self.document_name,
                               targets=[], document_offset=self.offset, document_length=len(self.document))
        observation['selected_archive_members'] = self.archive.namelist() if self.archive else []
        observation['tabs'] = [{'index': i, 'url': tab.url} for i, tab in enumerate(self.page.context.pages) if self.allowed(tab.url)]
        observation['frames'] = [
            {'index': i, 'url': frame.url, 'name': frame.name}
            for i, frame in enumerate(self.page.frames)
            if frame != self.page.main_frame and self.allowed(frame.url)
        ]
        return observation

    def allowed(self, url):
        from .planner import _site_for_url
        return _site_for_url(url, self.sites) is not None

    async def apply(self, action, site_id):
        from .planner import _apply, MAX_PAGE_TEXT
        kind = action['action']
        if kind == 'read_page':
            offset = action.get('offset')
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise ValueError('read_page offset must be a nonnegative integer')
            if self.document is not None:
                self.offset = min(offset, max(0, len(self.document) - 1))
            else:
                self.page_offset = offset
            return site_id, 'selected text offset on the current page or document'
        if kind == 'select_tab':
            index = action.get('index')
            tabs = self.page.context.pages
            if not isinstance(index, int) or not 0 <= index < len(tabs) or not self.allowed(tabs[index].url):
                raise ValueError('select a tab index from the current observation')
            self.page = tabs[index]
            self.frame = self.document = self.archive = None
            self.page_offset = 0
            return site_id, 'selected observed browser tab'
        if kind == 'select_frame':
            index = action.get('index')
            if not isinstance(index, int) or not 0 <= index < len(self.page.frames):
                raise ValueError('select a frame index from the current observation')
            frame = self.page.frames[index]
            if not self.allowed(frame.url):
                raise ValueError('frame outside the website allowlist')
            self.page_offset = 0
            self.frame = frame
            return site_id, 'selected frame'
        if kind == 'return_to_page':
            self.frame = self.document = self.archive = None
            return site_id, 'returned to the selected browser page'
        if kind == 'read_archive_member':
            member = action.get('member')
            if not self.archive or member not in self.archive.namelist():
                raise ValueError('select a member from the downloaded archive listing')
            info = self.archive.getinfo(member)
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError('archive member exceeds reading limit')
            self.document = parse_document(self.archive.read(member), member)
            self.document_name = member; self.offset = 0
            return site_id, 'read the selected archive member'
        if self.document is not None and kind == 'scroll':
            direction = action.get('direction')
            if direction not in {'up', 'down'}: raise ValueError('invalid document direction')
            self.offset = max(0, min(max(0, len(self.document) - 1), self.offset + (MAX_PAGE_TEXT if direction == 'down' else -MAX_PAGE_TEXT)))
            return site_id, 'paged the selected document'
        self.page_offset = 0
        if kind != 'click':
            if kind == 'open_site': self.frame = self.document = self.archive = None
            return await _apply(action, self.frame or self.page, self.sites, site_id, self.authorize)
        origin = self.page
        downloads = []; popups = []
        on_download = lambda item: downloads.append(item)
        on_popup = lambda item: popups.append(item)
        origin.on('download', on_download)
        origin.on('popup', on_popup)
        try:
            result = await _apply(action, self.frame or self.page, self.sites, site_id, self.authorize)
            if popups:
                popup = popups[-1]
                await popup.wait_for_load_state('domcontentloaded', timeout=10000)
                if not self.allowed(popup.url):
                    await popup.close()
                    raise ValueError('selected popup outside the website allowlist')
                self.page = popup; self.frame = None
                result = (site_id, 'opened the selected link in its new tab')
            if downloads:
                download = downloads[-1]
                if not self.allowed(download.url): raise ValueError('download outside the website allowlist')
                path = await download.path()
                if not path: raise ValueError('download did not produce a readable file')
                file = Path(path)
                if file.stat().st_size > MAX_FILE_BYTES: raise ValueError('download exceeds reading limit')
                data = file.read_bytes()
                self.source_url = download.url
                self.offset = 0
                self.document_name = download.suggested_filename
                if self.document_name.lower().endswith('.zip'):
                    archive = ZipFile(BytesIO(data))
                    if len(archive.infolist()) > 200: raise ValueError('archive has too many members')
                    self.archive = archive; self.document = None
                    return site_id, 'downloaded selected ZIP; choose a member from its listing'
                self.archive = None
                self.document = parse_document(data, self.document_name)
                return site_id, 'read the selected downloaded document'
            return result
        finally:
            # Listeners belong to the original page even when a popup becomes active.
            origin.remove_listener('download', on_download)
            origin.remove_listener('popup', on_popup)
