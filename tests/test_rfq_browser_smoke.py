"""Opt-in local Chromium smoke test. Never shipped in the agent package."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from hackathon_toolkit.rfq.browser import BrowserSession
from hackathon_toolkit.rfq.evidence import EvidenceBook

pytestmark = pytest.mark.skipif(os.environ.get("RFQ_BROWSER_SMOKE") != "1",
                                reason="Set RFQ_BROWSER_SMOKE=1 for the local Chromium smoke test")


async def test_real_cdp_controls_frames_popup_download_and_screenshot(tmp_path):
    from playwright.async_api import async_playwright
    executable = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
    assert executable, "Provide CHROME_BINARY for the optional smoke test"
    process = subprocess.Popen([executable, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--no-first-run", "--remote-debugging-port=0", f"--user-data-dir={tmp_path / 'profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        active_port = tmp_path / "profile" / "DevToolsActivePort"
        for _ in range(100):
            if active_port.exists():
                break
            if process.poll() is not None:
                pytest.fail("Local Chrome exited before exposing CDP")
            await asyncio.sleep(.05)
        port = active_port.read_text().splitlines()[0]
        async with async_playwright() as playwright:
            session = await BrowserSession.connect(playwright, [f"http://127.0.0.1:{port}"],
                                                    EvidenceBook(), ["https://synthetic.test"])
            page = session.page(0)
            await page.set_content('''<label>Name <input id="name"></label>
                <button onclick="document.querySelector('#status').textContent='Saved '+document.querySelector('#name').value">Save</button>
                <div id="status"></div>
                <button onclick="window.open('about:blank')">Popup</button>
                <a href="data:text/plain,Selected%20document" download="fixture.txt">Download</a>
                <iframe srcdoc="<p>Nested document</p>"></iframe>''')
            observed = await session.act("observe")
            input_ref = next(c["ref"] for c in observed["controls"] if c["tag"] == "INPUT")
            await session.act("fill", ref=input_ref, value="Synthetic user")
            observed = await session.act("observe")
            save_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Save")
            await session.act("click", ref=save_ref)
            observed = await session.act("observe")
            assert "Saved Synthetic user" in observed["text"]
            assert "Nested document" in (await session.act("observe", frame=1))["text"]
            assert (await session.act("screenshot"))["image_url"].startswith("data:image/png;base64,")
            observed = await session.act("observe")
            popup_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Popup")
            async with page.expect_popup():
                await session.act("click", ref=popup_ref)
            assert len(session.page_list()) == 2
            observed = await session.act("observe")
            download_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Download")
            download = await session.act("download", ref=download_ref)
            result = await session.act("read_download", download_id=download["download_id"])
            assert result["text"] == "Selected document"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
