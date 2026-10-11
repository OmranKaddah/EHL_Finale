"""Atira package entry point: model-directed research, then a signed website submission."""

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from . import browser, coordinator, planner, run_contract
from .deadline import RunClock
from .redact import RedactingStream, Redactor


async def main() -> int:
    task, token = run_contract.load_run()
    clock = RunClock(task)
    sites = planner.normalize_sites(task.get("access"))
    redactor = Redactor.from_runtime(os.environ, sites)
    redactor.add(token)
    sys.stdout = RedactingStream(sys.stdout, redactor)
    sys.stderr = RedactingStream(sys.stderr, redactor)
    worker_count = min(len(sites), browser.available_count(), 4)
    opened = []

    async def connect(index: int):
        browser_instance, page, owns_browser = await browser.connect(playwright, index)
        opened.append((browser_instance, owns_browser))
        return page

    async with async_playwright() as playwright:
        try:
            result = await asyncio.wait_for(coordinator.run(task, connect, worker_count, clock, redactor),
                                            clock.left() + 10)
        except asyncio.TimeoutError:
            result = {"status": "blocked", "phase": "unknown", "receipt": None, "reason": "run deadline reached"}
        finally:
            for browser_instance, owns_browser in opened:
                if owns_browser:
                    await browser_instance.close()
    if not token:
        # Local scouting only: a scrubbed result for diagnosis; never written in a platform run.
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/result.json").write_text(redactor.scrub(json.dumps(result, ensure_ascii=False, indent=2)))
    if coordinator.exit_code(result) == 0:
        print(f"Portal receipt {result['receipt']['receipt_id']} observed after signing. "
              "Eligibility is decided by the platform result, not by this log.", flush=True)
    else:
        print(f"No accepted submission: status={result.get('status')} phase={result.get('phase')} "
              f"reason={result.get('reason')}", flush=True)
    return coordinator.exit_code(result)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
