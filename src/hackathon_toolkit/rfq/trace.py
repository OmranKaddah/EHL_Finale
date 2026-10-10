"""Local action journal and four independently refreshed browser previews."""
import asyncio
from datetime import datetime, timezone
import html
import json
from pathlib import Path


class Trace:
    def __init__(self, directory, secrets):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets = secrets
        self.sequence = 0
        self.latest = {}
        self.progress = None
        self.browser_count = 0

    def clean(self, value):
        if isinstance(value, dict):
            return {k: ("[REDACTED]" if k in {"value", "password", "tan", "token", "image_url"}
                        else self.clean(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in sorted(set(self.secrets), key=len, reverse=True):
                if secret:
                    value = value.replace(secret, "[REDACTED]")
        return value

    def event(self, **data):
        record = self.clean({"at": datetime.now(timezone.utc).isoformat(), **data})
        path = self.directory / "actions.jsonl"
        with path.open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        path.chmod(0o600)
        return record

    async def capture(self, browser, pages=None):
        self.sequence += 1
        sequence = self.sequence
        self.browser_count = len(browser.browsers)
        rows = browser.page_list()
        if pages is None:
            selected = {}
            for row in rows:
                old = selected.get(row["browser"])
                if old is None or row.get("active") or (old["url"] == "about:blank" and row["url"] != "about:blank"):
                    selected[row["browser"]] = row
            rows = list(selected.values())
        for row in rows:
            if pages is not None and row["page"] not in pages:
                continue
            page = browser.page(row["page"])
            name = f"b{row['browser']}-p{row['page']}-{sequence:05}.png"
            try:
                async with asyncio.timeout(2):
                    await page.screenshot(path=str(self.directory / name), timeout=1800)
                (self.directory / name).chmod(0o600)
                self.latest[row["browser"]] = {**row, "image": name}
                self.event(kind="screenshot", **row, image=name)
            except Exception as exc:
                self.event(kind="screenshot_error", **row, error=type(exc).__name__)
        self._render()

    def update_progress(self):
        if self.progress:
            snapshot = self.clean(self.progress.snapshot())
            path = self.directory / "progress.json"
            temporary = self.directory / ".progress.json.tmp"
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
            temporary.chmod(0o600)
            temporary.replace(path)
        self._render()

    def _render(self):
        progress_html = ""
        if self.progress:
            snapshot = self.clean(self.progress.snapshot())
            rows = "".join(f"<tr><td>{html.escape(item['label'])}</td><td>{html.escape(item['status'])}</td></tr>"
                           for item in snapshot["milestones"].values())
            agents = "".join(f"<li>{html.escape(role)}: {html.escape(item['state'])} — "
                f"{html.escape(str(item.get('topic') or item.get('tool') or item.get('task') or ''))}</li>"
                for role, item in snapshot["agents"].items())
            progress_html = (f"<h2>{snapshot['completed']} / {snapshot['total']} milestones recorded; "
                f"{snapshot['remaining_count']} remaining</h2><p>Browser actions remaining: unknown. "
                "Research milestones are cited agent reports; review and receipt have independent validation.</p>"
                f"<table><thead><tr><th>Milestone</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
                f"<h2>Agent activity</h2><ul>{agents}</ul>")
        cards = []
        for index in range(self.browser_count):
            row = self.latest.get(index)
            body = (f'<p>Page {row["page"]}: {html.escape(row["url"])}</p>'
                    f'<a href="{row["image"]}"><img src="{row["image"]}"></a>' if row else '<p>Awaiting capture</p>')
            cards.append(f'<section><h2>Browser {index + 1}</h2>{body}</section>')
        (self.directory / "browsers.html").write_text(
            '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="3">'
            '<title>RFQ browser observations</title><style>body{font:14px system-ui;margin:16px;background:#eee}'
            'main{display:grid;grid-template-columns:1fr 1fr;gap:16px}section{background:white;padding:12px}'
            'img{width:100%}p{overflow-wrap:anywhere}</style><h1>RFQ browser observations</h1>'
            '<p>Latest captured states; browser numbers here are one-based. Action journal: actions.jsonl. '
            'Screenshots can contain business data and TANs; keep these artifacts private.</p>' + progress_html + '<main>' + ''.join(cards) + '</main>')
