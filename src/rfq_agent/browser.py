"""Attach to an Atira-provided browser in runs or launch Chromium locally."""

import json
import os


def cdp_urls(env=os.environ) -> list[str]:
    try:
        urls = [url for url in json.loads(env.get("CDP_URLS") or "[]") if isinstance(url, str)]
    except (TypeError, ValueError):
        urls = []
    return urls or ([env["CDP_URL"]] if env.get("CDP_URL") else [])


def available_count(env=os.environ) -> int:
    """Count run-provided browsers; locally permit the package's four-browser cap."""
    urls = cdp_urls(env)
    if urls:
        return len(urls)
    try:
        return max(1, min(4, int(env.get("BROWSER_COUNT", "4"))))
    except ValueError:
        return 4


async def connect(playwright, number: int = 0):
    """Return (browser, page, owns_browser); never launch a second run browser."""
    urls = cdp_urls()
    if urls:
        if number >= len(urls):
            raise RuntimeError(f"Browser {number + 1} was not provided; only {len(urls)} available")
        browser = await playwright.chromium.connect_over_cdp(urls[number])
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        owns_browser = False
    else:
        if os.environ.get("CHALLENGE_RUN_TOKEN"):
            raise RuntimeError("Run mode requires a platform-provided CDP browser")
        browser = await playwright.chromium.launch(headless=os.environ.get("HEADLESS") == "1")
        context = await browser.new_context()
        owns_browser = True
    # A dedicated tab prevents workers from mutating the same initial CDP page,
    # including when multiple endpoint aliases reach one browser.
    page = await context.new_page()
    return browser, page, owns_browser
