"""Opt-in local Chromium smoke test. Never shipped in the agent package."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from hackathon_toolkit.rfq.browser import BrowserSession
from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.trace import Trace

pytestmark = pytest.mark.skipif(os.environ.get("RFQ_BROWSER_SMOKE") != "1",
                                reason="Set RFQ_BROWSER_SMOKE=1 for the local Chromium smoke test")


async def test_four_sessions_sequential_changed_layouts_and_traces(tmp_path):
    from playwright.async_api import async_playwright
    executable = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
    processes, endpoints = [], []
    try:
        for index in range(4):
            profile = tmp_path / f"profile-{index}"
            process = subprocess.Popen([executable, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--no-first-run", "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            for _ in range(100):
                if (profile / "DevToolsActivePort").exists():
                    break
                await asyncio.sleep(.05)
            port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
            endpoints.append(f"http://127.0.0.1:{port}")
        async with async_playwright() as playwright:
            session = await BrowserSession.connect(playwright, endpoints, EvidenceBook(), ["https://synthetic.test"])
            trace = Trace(tmp_path / "artifacts", [])
            assert [p["browser"] for p in session.page_list()] == [0, 1, 2, 3]
            # No concurrent actions: test each independent browser and both layouts in order.
            for index in range(4):
                for variant in range(2):
                    page = session.page(index)
                    label = f"Find variant {variant} in session {index}"
                    fields = f'<label>{label}<input></label><button>Unrelated</button>'
                    table = f'<table><tr><th>Item</th><th>Pieces</th></tr><tr><td>TEST-{index}</td><td>{7 + variant}</td></tr></table>'
                    await page.set_content(fields + table if variant else table + fields)
                    observed = await session.act("observe", page=index)
                    ref = next(c["ref"] for c in observed["controls"] if c["label"] == label)
                    result = await session.act("fill", ref=ref, value=f"query-{variant}")
                    assert result["browser"] == index
                    assert f"query-{variant}" in session.book.observations[result["observation_id"]]["text"]
                    extracted = await session.act("extract", page=index)
                    assert extracted["tables"][0][1] == [f"TEST-{index}", str(7 + variant)]
                    trace.event(browser=index, observation_id=extracted["observation_id"], operation="extract")
                    await trace.capture(session, {index})
            assert len(trace.latest) == 4
            assert len(list((tmp_path / "artifacts").glob("*.png"))) == 8
            assert "Browser 4" in (tmp_path / "artifacts/browsers.html").read_text()
            # Explicit browser targeting must select that browser, not default to page zero.
            targeted = await session.act("observe", browser=3)
            assert targeted["browser"] == 3
            # Concurrent specialists must retain disjoint refs and their own field values.
            observations = await asyncio.gather(*(session.act("observe", page=i) for i in range(4)))
            refs = [next(c["ref"] for c in obs["controls"] if c["tag"] == "INPUT")
                    for obs in observations]
            assert len(set(refs)) == 4
            results = await asyncio.gather(*(session.act("fill", ref=ref, value=f"parallel-{i}")
                                             for i, ref in enumerate(refs)))
            for i, result in enumerate(results):
                assert result["browser"] == i
                assert f"parallel-{i}" in session.book.observations[result["observation_id"]]["text"]
            await asyncio.gather(*(trace.capture(session, {i}) for i in range(4)))
            assert len({row["image"] for row in trace.latest.values()}) == 4
            # Reuse a platform-provided blank tab; do not leave it beside an extra blank tab.
            await session.page(2).goto("about:blank")
            reused = await session.act("new_tab", browser=2)
            assert reused["page"] == 2 and reused["reused_blank"]
            assert len(session.page_list()) == 4
            with pytest.raises(ValueError, match="observed URL"):
                await session.act("navigate", page=0, url="https://synthetic.test/guessed-path")
            session.origins.add("https://another.test")
            session.known_urls.add("https://another.test")
            session.browser_origins[0] = "https://synthetic.test"
            with pytest.raises(ValueError, match="independently visible"):
                await session.act("navigate", page=0, url="https://another.test")
    finally:
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


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
                <label>Code <input id="code"></label>
                <label>Confirm <input id="confirm" type="checkbox"></label>
                <label>Level <input id="range" type="range" min="0" max="100" value="0"></label>
                <button onclick="document.querySelector('#status').textContent='Saved '+document.querySelector('#name').value">Save</button>
                <div id="status"></div>
                <button onclick="window.open('about:blank')">Popup</button>
                <a href="data:text/plain,Selected%20document" download="fixture.txt">Download</a>
                <dialog><p>Survey blocking page</p><button onclick="this.closest('dialog').close()">Dismiss</button></dialog>
                <iframe srcdoc="<p>Nested document</p>"></iframe>''')
            observed = await session.act("observe")
            input_refs = [c["ref"] for c in observed["controls"] if c["tag"] == "INPUT"]
            with pytest.raises(ValueError, match="checkbox control cannot be filled"):
                await session.act("fill_fields", fields=[
                    {"ref": input_refs[0], "value": "must stay empty"},
                    {"ref": input_refs[2], "value": "true"}])
            assert await page.locator("#name").input_value() == ""
            await session.act("click", ref=input_refs[2])
            assert await page.locator("#confirm").is_checked()
            observed = await session.act("observe")
            input_refs = [c["ref"] for c in observed["controls"] if c["tag"] == "INPUT"]
            observed = await session.act("fill_fields", fields=[
                {"ref": input_refs[0], "value": "Synthetic user"},
                {"ref": input_refs[1], "value": "42"}])
            assert observed["status"] == "action_completed"
            assert [c["value"] for c in observed["controls"] if c["tag"] == "INPUT"] == ["Synthetic user", "42", "on", "0"]
            range_ref = next(c["ref"] for c in observed["controls"] if c["type"] == "range")
            observed = await session.act("set_range", ref=range_ref, value="100")
            assert await page.locator("#range").input_value() == "100"
            save_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Save")
            observed = await session.act("click", ref=save_ref)
            assert "Saved Synthetic user" in observed["text"]
            # Overlay arrives after observation; the planned underlying action must not run.
            stale_save = next(c["ref"] for c in observed["controls"] if c["text"] == "Save")
            await page.locator("#status").evaluate("e => e.textContent='Not saved again'")
            await page.locator("dialog").evaluate("e => e.showModal()")
            modal = await session.act("click", ref=stale_save)
            assert modal["interrupted_action"]["executed"] is False
            assert await page.locator("#status").inner_text() == "Not saved again"
            assert "Survey blocking page" in modal["active_dialog"]
            assert [c["text"] for c in modal["controls"]] == ["Dismiss"]
            observed = await session.act("click", ref=modal["controls"][0]["ref"])
            assert observed["active_dialog"] is None
            await page.frames[1].set_content('<p>Nested document</p><input aria-label="Nested input">')
            nested = await session.act("observe", frame=1)
            assert "Nested document" in nested["text"]
            nested_ref = next(c["ref"] for c in nested["controls"] if c["tag"] == "INPUT")
            nested = await session.act("fill", ref=nested_ref, value="inside")
            assert nested["frames"][1]["frame"] == 1
            assert nested["controls"][0]["value"] == "inside"
            # A dialog confined to a sibling iframe does not obstruct main-frame controls.
            await page.frames[1].set_content('<dialog open><p>Frame-only notice</p><button>Continue</button></dialog>')
            main = await session.act("observe")
            save_ref = next(c["ref"] for c in main["controls"] if c["text"] == "Save")
            main = await session.act("click", ref=save_ref)
            assert "interrupted_action" not in main
            assert main["status"] == "action_completed"
            assert (await session.act("screenshot"))["image_url"].startswith("data:image/png;base64,")
            observed = await session.act("observe")
            popup_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Popup")
            async with page.expect_popup():
                await session.act("click", ref=popup_ref)
            assert len(session.page_list()) == 2
            popup = session.page(1)
            await popup.set_content('<input aria-label="Popup field">')
            popup_state = await session.act("observe", page=1)
            popup_ref = popup_state["controls"][0]["ref"]
            popup_state = await session.act("fill", ref=popup_ref, value="second page")
            assert popup_state["page"] == 1
            assert await popup.locator("input").input_value() == "second page"
            await session.act("screenshot", page=0)
            assert session.preferred_page(0) == 1
            observed = await session.act("observe", page=0)
            download_ref = next(c["ref"] for c in observed["controls"] if c["text"] == "Download")
            await session.act("observe", page=1)
            download = await session.act("download", ref=download_ref)
            result = await session.act("read_download", download_id=download["download_id"])
            assert result["text"] == "Selected document"
            session.downloads["csv"] = {"bytes": b'part;quantity\n"TEST;A";7\nB;9\n',
                                        "name": "selected.csv", "url": "https://synthetic.test/selected.csv"}
            structured = await session.act("parse_download", download_id="csv")
            assert structured["data"]["columns"] == ["part", "quantity"]
            assert structured["data"]["rows"] == [["TEST;A", "7"], ["B", "9"]]
            assert session.book.observations[structured["observation_id"]]["url"].startswith("https://synthetic.test/selected.csv")
            fresh = await session.act("new_context")
            assert fresh["page"] == 2
            await session.page(2).set_content("<p>Fresh context</p>")
            assert "Fresh context" in (await session.act("observe", page=2))["text"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def test_navigation_feedback_for_stalled_login_and_same_url_progress(tmp_path):
    from playwright.async_api import async_playwright
    executable = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
    assert executable, "Provide CHROME_BINARY for the optional smoke test"
    profile = tmp_path / "profile"
    process = subprocess.Popen([executable, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--no-first-run", "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        active_port = profile / "DevToolsActivePort"
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
            await page.set_content('''<button id="login">Log in</button>
                <button id="delayed" onclick="setTimeout(() => document.querySelector('#status').textContent='Delayed step', 250)">Delayed</button>
                <button id="next" onclick="document.querySelector('#status').textContent='Step 2'">Next</button>
                <button id="route" onclick="location.hash='receipt'">Submit</button>
                <p id="status"></p>
                <form><label>Required code <input required></label><button type="submit">Continue</button></form>''')
            # A paginated prior observation must not look like a page change.
            observed = await session.act("observe", offset=5)
            login = next(c["ref"] for c in observed["controls"] if c["text"] == "Log in")
            stalled = await session.act("click", ref=login)
            feedback = stalled["navigation_feedback"]
            assert feedback["outcome"] == "stalled"
            assert feedback["previous_url"] == feedback["current_url"]
            assert "Log in" in feedback["previous_page_text"]
            assert "required fields" in feedback["next"]

            await page.locator("#login").evaluate("e => e.onclick = () => document.querySelector('#status').textContent = 'Invalid password'")
            login = next(c["ref"] for c in stalled["controls"] if c["text"] == "Log in")
            validation = await session.act("click", ref=login)
            assert validation["navigation_feedback"]["outcome"] == "same_url_changed"
            assert "Invalid password" in validation["text"]

            delayed_ref = next(c["ref"] for c in validation["controls"] if c["text"] == "Delayed")
            delayed = await session.act("click", ref=delayed_ref, expect_navigation=True)
            assert delayed["navigation_feedback"]["outcome"] == "same_url_changed"
            assert "Delayed step" in delayed["text"]

            next_ref = next(c["ref"] for c in delayed["controls"] if c["text"] == "Next")
            advanced = await session.act("click", ref=next_ref)
            assert advanced["navigation_feedback"]["outcome"] == "same_url_changed"
            assert "Step 2" in advanced["text"]

            continue_ref = next(c["ref"] for c in advanced["controls"] if c["text"] == "Continue")
            invalid = await session.act("click", ref=continue_ref)
            assert invalid["navigation_feedback"]["outcome"] == "stalled"
            required = next(c for c in invalid["controls"] if c["tag"] == "INPUT" and c["required"])
            assert required["required"] and required["valid"] is False
            assert required["validationMessage"]

            submit = next(c["ref"] for c in invalid["controls"] if c["text"] == "Submit")
            navigated = await session.act("click", ref=submit, expect_navigation=True)
            assert navigated["navigation_feedback"]["outcome"] == "navigated"
            assert navigated["navigation_feedback"]["current_url"].endswith("#receipt")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
