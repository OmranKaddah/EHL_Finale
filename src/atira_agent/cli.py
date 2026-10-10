from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

from .browser import BrowserSession
from .config import Config
from .dashboard import Dashboard
from .models import QwenClient
from .orchestrator import Orchestrator
from .runtime import Deadline, load_run
from .telemetry import Redactor, Telemetry, configure_console, safe_error


async def run(args):
    redactor = Redactor(value for key, value in os.environ.items() if any(x in key for x in ("KEY", "TOKEN", "PASSWORD")))
    telemetry = Telemetry(Path(args.trace_dir), redactor)
    browser = model = dashboard = None
    try:
        config = Config.from_env()
        telemetry.structured_stdout = config.sandbox
        telemetry.debug = args.debug
        context = await load_run()
        for site in context.access:
            for value in site.credentials.values():
                redactor.add(value)
        telemetry.run_id = context.run_id
        deadline = Deadline(config.budget, config.reserve, context.expires_at if config.sandbox else None)
        telemetry.emit("run_started", mode="sandbox" if config.sandbox else "scouting", provider=config.provider,
                       model=config.model, remaining=deadline.remaining)
        model = QwenClient(config, telemetry)
        if args.model_smoke:
            telemetry.emit("model_smoke", result=await model.smoke())
            return 0
        if args.dashboard and not config.sandbox:
            dashboard = Dashboard(telemetry, args.dashboard_port)
            try:
                port = await dashboard.start()
                telemetry.emit("dashboard_started", url=f"http://127.0.0.1:{port}")
            except Exception as exc:
                telemetry.emit("dashboard_unavailable", error=safe_error(exc, redactor))
        browser = BrowserSession(config, context, telemetry, headful=True)
        await browser.start()
        controller = Orchestrator(context, config, browser, model, telemetry, deadline, os.environ.get("CHALLENGE_RUN_TOKEN"))
        success = await controller.run_loop(max_steps=args.max_steps)
        telemetry.artifact("summary.json", {"success": success, "submission": controller.submission.state,
                           "receipt": controller.submission.receipt, "remaining": deadline.remaining,
                           "input_tokens": model.input_tokens, "output_tokens": model.output_tokens})
        return 0 if success else 2
    except Exception as exc:
        telemetry.emit("run_failed", error=safe_error(exc, redactor))
        return 1
    finally:
        for resource in (dashboard, browser, model):
            if resource:
                try:
                    await asyncio.wait_for(resource.close(), timeout=2)
                except Exception:
                    pass
        telemetry.close()


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="Atira model-directed RFQ agent")
    parser.add_argument("--debug", action="store_true", help="Detailed redacted JSONL is always enabled")
    parser.add_argument("--headful", action="store_true", help="Local browser is always visible")
    parser.add_argument("--trace-dir", default="artifacts/" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--dashboard-port", type=int, default=int(os.environ.get("ATIRA_DASHBOARD_PORT", "8787")))
    parser.add_argument("--model-smoke", action="store_true")
    parser.add_argument("--max-steps", type=int, default=450)
    args = parser.parse_args()
    return asyncio.run(run(args))
