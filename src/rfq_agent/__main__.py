"""Atira package entry point: run the model-directed exploration MVP."""

import asyncio
import sys

from playwright.async_api import async_playwright

from . import browser, planner, run_contract
from .evidence import EvidenceLedger


async def main() -> int:
    task, _token = run_contract.load_run()
    sites = planner.normalize_sites(task.get("access"))
    worker_count = min(len(sites), browser.available_count(), 4)
    if worker_count < 1:
        raise RuntimeError("No investigation workers can be started")
    assignments = await planner.plan_assignments(task, sites, worker_count)
    print(f"Starting {worker_count} model-directed investigations across {worker_count} browsers", flush=True)
    ledger = EvidenceLedger()

    async def investigate(index: int, assignment: dict):
        browser_instance, page, owns_browser = await browser.connect(playwright, index)
        try:
            return await planner.run_planner(task, page, assignment, ledger)
        finally:
            if owns_browser:
                await browser_instance.close()

    async with async_playwright() as playwright:
        results = await asyncio.gather(
            *(investigate(index, assignment) for index, assignment in enumerate(assignments)),
            return_exceptions=True,
        )
    completed = sum(isinstance(result, dict) for result in results)
    failed = len(results) - completed
    for result in results:
        if isinstance(result, dict):
            print(
                f"[{result['site_id']}] stopped after {result['steps']} steps; "
                f"evidence records={result['evidence_count']}; reason={result['stop_reason']}",
                flush=True,
            )
        else:
            print(f"Investigator failed ({type(result).__name__})", flush=True)
    evidence_count = len(await ledger.snapshot())
    print(
        f"Exploration finished: {completed} investigators completed, {failed} failed; "
        f"selected evidence records: {evidence_count}. No bid was submitted.",
        flush=True,
    )
    return 0 if completed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
