from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from .config import Config
from .dashboard import Dashboard
from .multi_agent import MultiAgentCoordinator, benchmark_schedule
from .runtime import Deadline, load_run
from .telemetry import Redactor, Telemetry, configure_console, safe_error


async def run(args):
    started = time.monotonic()
    redactor = Redactor(value for key, value in os.environ.items() if any(x in key for x in ("KEY", "TOKEN", "PASSWORD")))
    telemetry = Telemetry(Path(args.trace_dir), redactor)
    coordinator = dashboard = None
    try:
        if args.benchmark:
            telemetry.emit("architecture_benchmark", result=benchmark_schedule())
            return 0
        config = Config.from_env()
        telemetry.structured_stdout = config.sandbox
        telemetry.debug = args.debug
        context = await load_run()
        for site in context.access:
            for value in site.credentials.values():
                redactor.add(value)
        telemetry.run_id = context.run_id
        deadline = Deadline(config.budget, config.reserve, context.expires_at if config.sandbox else None, started=started)
        telemetry.emit("run_started", mode="sandbox" if config.sandbox else "scouting", provider=config.provider,
                       model=config.model, remaining=deadline.remaining)
        if args.model_smoke:
            from .models import QwenClient
            model = QwenClient(config, telemetry)
            telemetry.emit("model_smoke", result=await model.smoke())
            await model.close()
            return 0
        coordinator = MultiAgentCoordinator(context, config, deadline, telemetry, Path(args.trace_dir), os.environ.get("CHALLENGE_RUN_TOKEN"))
        await coordinator.start()
        coordinator.set_research_focus(args.focus)
        if args.dashboard and not config.sandbox:
            dashboard = Dashboard(coordinator.telemetries, args.dashboard_port)
            try:
                port = await dashboard.start()
                telemetry.emit("dashboard_started", url=f"http://127.0.0.1:{port}")
            except Exception as exc:
                telemetry.emit("dashboard_unavailable", error=safe_error(exc, redactor))
        focus_roles = (args.focus,) if args.focus else None
        failed = await coordinator.investigate_roles(steps=max(1, min(args.max_steps, 96)), roles=focus_roles)
        if args.research_only:
            telemetry.artifact("summary.json", {"success": False, "research_only": True,
                               "failed_agents": failed, "remaining": deadline.remaining,
                               "benchmark": benchmark_schedule()})
            telemetry.emit("research_complete", failed_agents=failed, remaining=deadline.remaining)
            return 0
        success = await coordinator.calculate_and_submit(steps=max(1, args.max_steps - 96))
        telemetry.artifact("summary.json", {"success": success, "failed_agents": failed,
                           "submission": coordinator.submission.state, "receipt": coordinator.submission.receipt,
                           "remaining": deadline.remaining, "benchmark": benchmark_schedule()})
        return 0 if success else 2
    except Exception as exc:
        telemetry.emit("run_failed", error=safe_error(exc, redactor))
        return 1
    finally:
        for resource in (dashboard, coordinator):
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
    parser.add_argument("--benchmark", action="store_true", help="Report a deterministic dependency-scheduling baseline comparison")
    parser.add_argument("--research-only", action="store_true", help="Investigate and publish evidence without calculating or submitting")
    parser.add_argument("--focus", choices=("tender", "specifications", "erp", "mail"),
                        help="Run only one specialist during a research rehearsal")
    parser.add_argument("--max-steps", type=int, default=450)
    args = parser.parse_args()
    return asyncio.run(run(args))
