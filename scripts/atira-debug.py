"""Read official Atira diagnostics through the installed CLI's MCP transport."""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

from atira_agent.telemetry import Redactor, configure_console


def main():
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=["list", "get_run", "diagnose_run", "run_logs", "run_profile", "run_llm_calls", "compare_runs", "run_screenshot"])
    parser.add_argument("--args", default="{}", help="JSON arguments; use list to see exact schemas")
    parser.add_argument("--run-id", help="Convenience argument for run tools")
    parser.add_argument("--at", help="Recording time for run_screenshot, such as 19:50")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cli = shutil.which("atira")
    if os.name == "nt":
        install = Path(os.environ["LOCALAPPDATA"]) / "atira"
        command = [str(install / "node/node.exe"), str(install / "atira.mjs"), "mcp"]
    elif cli:
        command = [cli, "mcp"]
    else:
        parser.error("Installed Atira CLI not found")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8")
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                pass
    threading.Thread(target=read, daemon=True).start()

    def send(message):
        process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        process.stdin.flush()

    def request(identifier, method, params):
        send({"id": identifier, "method": method, "params": params})
        while True:
            message = messages.get(timeout=55)
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]
    try:
        request(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "atira-local-debug", "version": "0.1"}})
        send({"method": "notifications/initialized"})
        arguments = json.loads(args.args)
        if args.run_id:
            arguments["run_id"] = args.run_id
        if args.at:
            arguments["at"] = args.at
        result = request(2, "tools/list", {}) if args.tool == "list" else request(
            2, "tools/call", {"name": args.tool, "arguments": arguments})
        redactor = Redactor(v for k, v in os.environ.items() if any(x in k for x in ("TOKEN", "KEY", "PASSWORD")))
        text = json.dumps(redactor.clean(result), ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
